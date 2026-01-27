"""Enterprise OTLP trace client implementation."""

import hashlib
import logging
import random
import socket
import threading
import uuid
from collections import deque
from collections.abc import Sequence
from datetime import datetime
from typing import Final, cast

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

INVALID_SPAN_ID: Final[int] = 0x0000000000000000
INVALID_TRACE_ID: Final[int] = 0x00000000000000000000000000000000
DEFAULT_TIMEOUT: Final[int] = 5
DEFAULT_MAX_QUEUE_SIZE: Final[int] = 1000
DEFAULT_SCHEDULE_DELAY_SEC: Final[int] = 5
DEFAULT_MAX_EXPORT_BATCH_SIZE: Final[int] = 50

logger = logging.getLogger(__name__)


class EnterpriseTraceClient:
    """OTLP-based trace client for enterprise deployments."""

    def __init__(
        self,
        service_name: str,
        endpoint: str,
        token: str | None = None,
        max_queue_size: int = DEFAULT_MAX_QUEUE_SIZE,
        schedule_delay_sec: int = DEFAULT_SCHEDULE_DELAY_SEC,
        max_export_batch_size: int = DEFAULT_MAX_EXPORT_BATCH_SIZE,
    ):
        self.endpoint = endpoint
        self.token = token

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
