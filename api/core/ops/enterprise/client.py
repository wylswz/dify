"""Enterprise OTLP trace client implementation with metrics support."""

import hashlib
import json
import logging
import random
import socket
import threading
import uuid
from collections import deque
from collections.abc import Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Final, cast

import httpx
from opentelemetry import trace as trace_api
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.semconv.resource import ResourceAttributes
from opentelemetry.trace import Link, SpanContext, TraceFlags

from configs import dify_config
from core.ops.enterprise.entities.enterprise_trace_entity import SpanData
from core.ops.enterprise.entities.semconv import ENTERPRISE_SERVICE_FEATURE

if TYPE_CHECKING:
    from opentelemetry.metrics import Meter
    from opentelemetry.metrics._internal.instrument import Histogram
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import MetricReader

INVALID_SPAN_ID: Final[int] = 0x0000000000000000
INVALID_TRACE_ID: Final[int] = 0x00000000000000000000000000000000
DEFAULT_TIMEOUT: Final[int] = 5
DEFAULT_MAX_QUEUE_SIZE: Final[int] = 1000
DEFAULT_SCHEDULE_DELAY_SEC: Final[int] = 5
DEFAULT_MAX_EXPORT_BATCH_SIZE: Final[int] = 50
DEFAULT_METRICS_EXPORT_INTERVAL_SEC: Final[int] = 10

# Metrics names
LLM_OPERATION_DURATION: Final[str] = "gen_ai.client.operation.duration"
GEN_AI_TOKEN_USAGE: Final[str] = "gen_ai.client.token.usage"
GEN_AI_SERVER_TIME_TO_FIRST_TOKEN: Final[str] = "gen_ai.server.time_to_first_token"
GEN_AI_STREAMING_TIME_TO_GENERATE: Final[str] = "llm.streaming.time_to_generate"
GEN_AI_TRACE_DURATION: Final[str] = "gen_ai.trace.duration"

logger = logging.getLogger(__name__)


class EnterpriseTraceClient:
    """OTLP-based trace client for enterprise deployments with metrics support."""

    def __init__(
        self,
        service_name: str,
        endpoint: str,
        token: str | None = None,
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
        schedule_delay_sec: int = DEFAULT_SCHEDULE_DELAY_SEC,
        max_export_batch_size: int = DEFAULT_MAX_EXPORT_BATCH_SIZE,
        metrics_export_interval_sec: int = DEFAULT_METRICS_EXPORT_INTERVAL_SEC,
    ):
        self.endpoint = endpoint
        self.token = token
        self.service_name = service_name
        self.metrics_export_interval_sec = metrics_export_interval_sec

        self.resource = Resource(
            attributes={
                ResourceAttributes.SERVICE_NAME: service_name,
                ResourceAttributes.SERVICE_VERSION: f"dify-{dify_config.project.version}-{dify_config.COMMIT_SHA}",
                ResourceAttributes.DEPLOYMENT_ENVIRONMENT: f"{dify_config.DEPLOY_ENV}-{dify_config.EDITION}",
                ResourceAttributes.HOST_NAME: socket.gethostname(),
                ENTERPRISE_SERVICE_FEATURE: "genai_app",
            }
        )
        self.span_builder = SpanBuilder(self.resource)

        # Configure headers for authentication if token is provided
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"

        self.exporter = OTLPSpanExporter(endpoint=endpoint, headers=headers)

        self.max_queue_size = max_queue_size
        self.schedule_delay_sec = schedule_delay_sec
        self.max_export_batch_size = max_export_batch_size

        self.queue: deque[ReadableSpan] = deque(maxlen=max_queue_size)
        self.condition = threading.Condition(threading.Lock())
        self.done = False

        self.worker_thread = threading.Thread(target=self._worker, daemon=True)
        self.worker_thread.start()

        self._spans_dropped = False

        # Initialize metrics
        self.meter: Meter | None = None
        self.meter_provider: MeterProvider | None = None
        self.hist_llm_duration: Histogram | None = None
        self.hist_token_usage: Histogram | None = None
        self.hist_time_to_first_token: Histogram | None = None
        self.hist_time_to_generate: Histogram | None = None
        self.hist_trace_duration: Histogram | None = None
        self.metric_reader: MetricReader | None = None

        self._init_metrics(endpoint, headers)

    def export(self, spans: Sequence[ReadableSpan]) -> None:
        """Export spans directly."""
        self.exporter.export(spans)

    def api_check(self) -> bool:
        """Check if the OTLP endpoint is reachable."""
        try:
            headers = {}
            if self.token:
                headers["Authorization"] = f"Bearer {self.token}"

            response = httpx.head(self.endpoint, headers=headers, timeout=DEFAULT_TIMEOUT)
            # OTLP endpoints typically return 405 for HEAD requests or 200 for health checks
            if response.status_code in (200, 405):
                return True
            else:
                logger.warning("Enterprise OTLP API check failed: Unexpected status code: %s", response.status_code)
                return False
        except httpx.RequestError as e:
            logger.warning("Enterprise OTLP API check failed: %s", str(e))
            raise ValueError(f"Enterprise OTLP API check failed: {str(e)}")

    def get_project_url(self) -> str:
        """Return the project URL (base endpoint for reference)."""
        return self.endpoint

    def add_span(self, span_data: SpanData | None) -> None:
        """Add a span to the export queue."""
        if span_data is None:
            return

        logger.debug("[Enterprise OTLP] Adding span: %s (trace_id=%s)", span_data.name, hex(span_data.trace_id))
        span: ReadableSpan = self.span_builder.build_span(span_data)
        with self.condition:
            if len(self.queue) == self.max_queue_size:
                if not self._spans_dropped:
                    logger.warning("Queue is full, likely spans will be dropped.")
                    self._spans_dropped = True

            self.queue.appendleft(span)
            if len(self.queue) >= self.max_export_batch_size:
                self.condition.notify()

    def _worker(self) -> None:
        """Background worker thread for exporting spans."""
        while not self.done:
            with self.condition:
                if len(self.queue) < self.max_export_batch_size and not self.done:
                    self.condition.wait(timeout=self.schedule_delay_sec)
            self._export_batch()

    def _export_batch(self) -> None:
        """Export a batch of spans."""
        spans_to_export: list[ReadableSpan] = []
        with self.condition:
            while len(spans_to_export) < self.max_export_batch_size and self.queue:
                spans_to_export.append(self.queue.pop())

        if spans_to_export:
            try:
                logger.info("[Enterprise OTLP] Exporting %d spans to %s", len(spans_to_export), self.endpoint)
                self.exporter.export(spans_to_export)
                logger.info("[Enterprise OTLP] Successfully exported %d spans", len(spans_to_export))
            except Exception as e:
                logger.warning("[Enterprise OTLP] Error exporting spans: %s", e)

    def shutdown(self) -> None:
        """Shutdown the trace client gracefully."""
        with self.condition:
            self.done = True
            self.condition.notify_all()
        self.worker_thread.join()
        self._export_batch()
        self.exporter.shutdown()

        # Shutdown metrics
        if self.meter_provider is not None:
            try:
                self.meter_provider.shutdown()  # type: ignore[attr-defined]
            except Exception:
                logger.debug("[Enterprise OTLP] Error shutting down meter provider", exc_info=True)

        if self.metric_reader is not None:
            try:
                self.metric_reader.shutdown()  # type: ignore[attr-defined]
            except Exception:
                logger.debug("[Enterprise OTLP] Error shutting down metric reader", exc_info=True)

    def _init_metrics(self, endpoint: str, headers: dict[str, str]) -> None:
        """Initialize OpenTelemetry metrics."""
        try:
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter as HttpMetricExporter,
            )
            from opentelemetry.sdk.metrics import Histogram, MeterProvider
            from opentelemetry.sdk.metrics.export import AggregationTemporality, PeriodicExportingMetricReader

            # Build metrics endpoint (replace /traces with /metrics if present)
            metrics_endpoint = endpoint.replace("/v1/traces", "/v1/metrics")

            # Use delta aggregation temporality
            preferred_temporality: dict[type, AggregationTemporality] = {Histogram: AggregationTemporality.DELTA}

            try:
                metric_exporter = HttpMetricExporter(
                    endpoint=metrics_endpoint,
                    headers=headers,
                    preferred_temporality=preferred_temporality,
                )
            except Exception:
                metric_exporter = HttpMetricExporter(
                    endpoint=metrics_endpoint,
                    headers=headers,
                )

            metric_reader = PeriodicExportingMetricReader(
                metric_exporter, export_interval_millis=self.metrics_export_interval_sec * 1000
            )

            provider = MeterProvider(resource=self.resource, metric_readers=[metric_reader])
            self.meter_provider = provider
            self.meter = provider.get_meter("dify-enterprise", dify_config.project.version)

            # LLM operation duration histogram
            self.hist_llm_duration = self.meter.create_histogram(
                name=LLM_OPERATION_DURATION,
                unit="s",
                description="LLM operation duration (seconds)",
            )

            # Token usage histogram
            self.hist_token_usage = self.meter.create_histogram(
                name=GEN_AI_TOKEN_USAGE,
                unit="token",
                description="Number of tokens used in prompt and completions",
            )

            # Time to first token histogram
            self.hist_time_to_first_token = self.meter.create_histogram(
                name=GEN_AI_SERVER_TIME_TO_FIRST_TOKEN,
                unit="s",
                description="Time to first token for streaming LLM responses (seconds)",
            )

            # Time to generate histogram
            self.hist_time_to_generate = self.meter.create_histogram(
                name=GEN_AI_STREAMING_TIME_TO_GENERATE,
                unit="s",
                description="Total time to generate streaming LLM responses (seconds)",
            )

            # Trace duration histogram
            self.hist_trace_duration = self.meter.create_histogram(
                name=GEN_AI_TRACE_DURATION,
                unit="s",
                description="End-to-end GenAI trace duration (seconds)",
            )

            self.metric_reader = metric_reader
            logger.info("[Enterprise OTLP] Metrics initialized with endpoint: %s", metrics_endpoint)

        except Exception:
            logger.exception("[Enterprise OTLP] Metrics initialization failed; metrics disabled")
            self.meter = None
            self.meter_provider = None
            self.hist_llm_duration = None
            self.hist_token_usage = None
            self.hist_time_to_first_token = None
            self.hist_time_to_generate = None
            self.hist_trace_duration = None
            self.metric_reader = None

    # Metrics recording API
    def record_llm_duration(self, latency_seconds: float, attributes: dict[str, str] | None = None) -> None:
        """Record LLM operation duration histogram in seconds."""
        try:
            if self.hist_llm_duration is None:
                return
            attrs: dict[str, str] = {}
            if attributes:
                for k, v in attributes.items():
                    attrs[k] = str(v) if not isinstance(v, (str, int, float, bool)) else v  # type: ignore[assignment]

            logger.debug(
                "[Enterprise Metrics] Metric: %s | Value: %.4f | Attributes: %s",
                LLM_OPERATION_DURATION,
                latency_seconds,
                json.dumps(attrs, ensure_ascii=False),
            )

            self.hist_llm_duration.record(latency_seconds, attrs)  # type: ignore[attr-defined]
        except Exception:
            logger.debug("[Enterprise OTLP] Failed to record LLM duration", exc_info=True)

    def record_token_usage(
        self,
        token_count: int,
        token_type: str,
        operation_name: str,
        request_model: str,
        response_model: str,
        server_address: str,
        provider: str,
    ) -> None:
        """Record token usage histogram.

        Args:
            token_count: Number of tokens used
            token_type: "input" or "output"
            operation_name: Operation name (e.g., "chat")
            request_model: Model used in request
            response_model: Model used in response
            server_address: Server address
            provider: Model provider name
        """
        try:
            if self.hist_token_usage is None:
                return

            attributes = {
                "gen_ai.operation.name": operation_name,
                "gen_ai.request.model": request_model,
                "gen_ai.response.model": response_model,
                "gen_ai.system": provider,
                "gen_ai.token.type": token_type,
                "server.address": server_address,
            }

            logger.debug(
                "[Enterprise Metrics] Metric: %s | Value: %d | Attributes: %s",
                GEN_AI_TOKEN_USAGE,
                token_count,
                json.dumps(attributes, ensure_ascii=False),
            )

            self.hist_token_usage.record(token_count, attributes)  # type: ignore[attr-defined]
        except Exception:
            logger.debug("[Enterprise OTLP] Failed to record token usage", exc_info=True)

    def record_time_to_first_token(
        self, ttft_seconds: float, provider: str, model: str, operation_name: str = "chat"
    ) -> None:
        """Record time to first token histogram."""
        try:
            if self.hist_time_to_first_token is None:
                return

            attributes = {
                "gen_ai.operation.name": operation_name,
                "gen_ai.system": provider,
                "gen_ai.request.model": model,
                "gen_ai.response.model": model,
                "stream": "true",
            }

            logger.debug(
                "[Enterprise Metrics] Metric: %s | Value: %.4f | Attributes: %s",
                GEN_AI_SERVER_TIME_TO_FIRST_TOKEN,
                ttft_seconds,
                json.dumps(attributes, ensure_ascii=False),
            )

            self.hist_time_to_first_token.record(ttft_seconds, attributes)  # type: ignore[attr-defined]
        except Exception:
            logger.debug("[Enterprise OTLP] Failed to record time to first token", exc_info=True)

    def record_time_to_generate(
        self, ttg_seconds: float, provider: str, model: str, operation_name: str = "chat"
    ) -> None:
        """Record time to generate histogram."""
        try:
            if self.hist_time_to_generate is None:
                return

            attributes = {
                "gen_ai.operation.name": operation_name,
                "gen_ai.system": provider,
                "gen_ai.request.model": model,
                "gen_ai.response.model": model,
                "stream": "true",
            }

            logger.debug(
                "[Enterprise Metrics] Metric: %s | Value: %.4f | Attributes: %s",
                GEN_AI_STREAMING_TIME_TO_GENERATE,
                ttg_seconds,
                json.dumps(attributes, ensure_ascii=False),
            )

            self.hist_time_to_generate.record(ttg_seconds, attributes)  # type: ignore[attr-defined]
        except Exception:
            logger.debug("[Enterprise OTLP] Failed to record time to generate", exc_info=True)

    def record_trace_duration(self, duration_seconds: float, attributes: dict[str, str] | None = None) -> None:
        """Record end-to-end trace duration histogram in seconds."""
        try:
            if self.hist_trace_duration is None:
                return

            attrs: dict[str, str] = {}
            if attributes:
                for k, v in attributes.items():
                    attrs[k] = str(v) if not isinstance(v, (str, int, float, bool)) else v  # type: ignore[assignment]

            logger.debug(
                "[Enterprise Metrics] Metric: %s | Value: %.4f | Attributes: %s",
                GEN_AI_TRACE_DURATION,
                duration_seconds,
                json.dumps(attrs, ensure_ascii=False),
            )

            self.hist_trace_duration.record(duration_seconds, attrs)  # type: ignore[attr-defined]
        except Exception:
            logger.debug("[Enterprise OTLP] Failed to record trace duration", exc_info=True)


class SpanBuilder:
    """Builds OpenTelemetry ReadableSpan objects from SpanData."""

    def __init__(self, resource: Resource) -> None:
        self.resource = resource
        self.instrumentation_scope = InstrumentationScope(
            "dify.enterprise.tracer",
            "",
            None,
            None,
        )

    def build_span(self, span_data: SpanData) -> ReadableSpan:
        """Build a ReadableSpan from SpanData."""
        span_context = trace_api.SpanContext(
            trace_id=span_data.trace_id,
            span_id=span_data.span_id,
            is_remote=False,
            trace_flags=trace_api.TraceFlags(trace_api.TraceFlags.SAMPLED),
            trace_state=None,
        )

        parent_span_context = None
        if span_data.parent_span_id is not None:
            parent_span_context = trace_api.SpanContext(
                trace_id=span_data.trace_id,
                span_id=span_data.parent_span_id,
                is_remote=False,
                trace_flags=trace_api.TraceFlags(trace_api.TraceFlags.SAMPLED),
                trace_state=None,
            )

        span = ReadableSpan(
            name=span_data.name,
            context=span_context,
            parent=parent_span_context,
            resource=self.resource,
            attributes=span_data.attributes,
            events=span_data.events,
            links=span_data.links,
            kind=span_data.span_kind,
            status=span_data.status,
            start_time=span_data.start_time,
            end_time=span_data.end_time,
            instrumentation_scope=self.instrumentation_scope,
        )
        return span


def create_link(trace_id_str: str) -> Link:
    """Create a Link to another trace from a hex trace ID string."""
    placeholder_span_id = INVALID_SPAN_ID
    try:
        trace_id = int(trace_id_str, 16)
    except ValueError as e:
        raise ValueError(f"Invalid trace ID format: {trace_id_str}") from e

    span_context = SpanContext(
        trace_id=trace_id, span_id=placeholder_span_id, is_remote=False, trace_flags=TraceFlags(TraceFlags.SAMPLED)
    )

    return Link(span_context)


def generate_span_id() -> int:
    """Generate a random 64-bit span ID."""
    span_id = random.getrandbits(64)
    while span_id == INVALID_SPAN_ID:
        span_id = random.getrandbits(64)
    return span_id


def convert_to_trace_id(uuid_v4: str | None) -> int:
    """Convert a UUID string to a 128-bit trace ID."""
    if uuid_v4 is None:
        raise ValueError("UUID cannot be None")
    try:
        uuid_obj = uuid.UUID(uuid_v4)
        return cast(int, uuid_obj.int)
    except ValueError as e:
        raise ValueError(f"Invalid UUID input: {uuid_v4}") from e


def convert_string_to_id(string: str | None) -> int:
    """Convert an arbitrary string to a 64-bit ID using SHA256."""
    if not string:
        return generate_span_id()
    hash_bytes = hashlib.sha256(string.encode("utf-8")).digest()
    return int.from_bytes(hash_bytes[:8], byteorder="big", signed=False)


def convert_to_span_id(uuid_v4: str | None, span_type: str) -> int:
    """Convert a UUID string and span type to a 64-bit span ID."""
    if uuid_v4 is None:
        raise ValueError("UUID cannot be None")
    try:
        uuid_obj = uuid.UUID(uuid_v4)
    except ValueError as e:
        raise ValueError(f"Invalid UUID input: {uuid_v4}") from e
    combined_key = f"{uuid_obj.hex}-{span_type}"
    return convert_string_to_id(combined_key)


def convert_hex_trace_id_to_int(trace_id_hex: str | None) -> int:
    """Convert a hex trace ID string (from BaseTraceInfo.trace_id) to a 128-bit integer."""
    if trace_id_hex is None:
        raise ValueError("Trace ID cannot be None")
    try:
        # Handle both with and without '0x' prefix
        if trace_id_hex.startswith("0x") or trace_id_hex.startswith("0X"):
            return int(trace_id_hex, 16)
        # First try as hex string
        return int(trace_id_hex, 16)
    except ValueError:
        # If it's a UUID format, convert it
        try:
            uuid_obj = uuid.UUID(trace_id_hex)
            return cast(int, uuid_obj.int)
        except ValueError as e:
            raise ValueError(f"Invalid trace ID format: {trace_id_hex}") from e


def convert_datetime_to_nanoseconds(dt: datetime | None) -> int | None:
    """Convert a datetime to nanoseconds since epoch."""
    if dt is None:
        return None
    timestamp_in_seconds = dt.timestamp()
    return int(timestamp_in_seconds * 1e9)
