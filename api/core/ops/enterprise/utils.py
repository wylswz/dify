"""Utility functions for Enterprise OTLP tracing."""

import json
import logging
from typing import Any

from opentelemetry import trace as trace_api
from opentelemetry.trace import Link, SpanContext, Status, StatusCode, TraceFlags

from core.ops.enterprise.client import INVALID_SPAN_ID, convert_hex_trace_id_to_int
from core.ops.enterprise.entities.semconv import (
    DIFY_TRACE_ID,
    GEN_AI_FRAMEWORK,
    GEN_AI_SESSION_ID,
    GEN_AI_SPAN_KIND,
    GEN_AI_USER_ID,
    INPUT_VALUE,
    OUTPUT_VALUE,
    GenAISpanKind,
)
from core.workflow.entities import WorkflowNodeExecution

logger = logging.getLogger(__name__)


def serialize_json_data(data: Any) -> str:
    """Serialize data to JSON string, handling various types."""
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    try:
        return json.dumps(data, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return str(data)


def create_common_span_attributes(
    *,
    session_id: str,
    user_id: str,
    span_kind: GenAISpanKind,
    inputs: str,
    outputs: str,
    dify_trace_id: str | None = None,
) -> dict[str, str]:
    """Create common span attributes for all span types."""
    attributes = {
        GEN_AI_SESSION_ID: session_id,
        GEN_AI_USER_ID: user_id,
        GEN_AI_SPAN_KIND: span_kind.value,
        GEN_AI_FRAMEWORK: "dify",
        INPUT_VALUE: inputs,
        OUTPUT_VALUE: outputs,
    }
    if dify_trace_id:
        attributes[DIFY_TRACE_ID] = dify_trace_id
    return attributes


def create_status_from_error(error: str | None) -> Status:
    """Create an OpenTelemetry Status from an error string."""
    if error:
        return Status(StatusCode.ERROR, description=error)
    return Status(StatusCode.OK)


def create_links_from_trace_id(trace_id: str | None) -> list[trace_api.Link]:
    """Create links from a trace ID string."""
    if not trace_id:
        return []

    try:
        trace_id_int = convert_hex_trace_id_to_int(trace_id)
        span_context = SpanContext(
            trace_id=trace_id_int,
            span_id=INVALID_SPAN_ID,
            is_remote=False,
            trace_flags=TraceFlags(TraceFlags.SAMPLED),
        )
        return [Link(span_context)]
    except (ValueError, TypeError) as e:
        logger.debug("Failed to create link from trace_id %s: %s", trace_id, e)
        return []


def get_workflow_node_status(node_execution: WorkflowNodeExecution) -> Status:
    """Get OpenTelemetry Status from workflow node execution."""
    if node_execution.status == "failed":
        error_msg = node_execution.error or "Unknown error"
        return Status(StatusCode.ERROR, description=error_msg)
    return Status(StatusCode.OK)


def get_user_id_from_message_data(message_data: dict[str, Any] | Any) -> str:
    """Extract user ID from message data."""
    if isinstance(message_data, dict):
        user_id = message_data.get("from_end_user_id") or message_data.get("from_account_id") or ""
        return str(user_id)
    # Handle object with attributes
    user_id = getattr(message_data, "from_end_user_id", None) or getattr(message_data, "from_account_id", None) or ""
    return str(user_id)


def extract_retrieval_documents(documents: Any) -> list[dict[str, Any]]:
    """Extract retrieval documents into a standardized format."""
    if not documents:
        return []

    result = []
    if isinstance(documents, list):
        for doc in documents:
            if isinstance(doc, dict):
                result.append(
                    {
                        "content": doc.get("content", doc.get("page_content", "")),
                        "metadata": doc.get("metadata", {}),
                        "score": doc.get("score", doc.get("relevance_score")),
                    }
                )
            else:
                # Handle object with attributes
                result.append(
                    {
                        "content": getattr(doc, "content", getattr(doc, "page_content", "")),
                        "metadata": getattr(doc, "metadata", {}),
                        "score": getattr(doc, "score", getattr(doc, "relevance_score", None)),
                    }
                )
    return result


def format_retrieval_documents(documents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Format retrieval documents for semantic conventions."""
    formatted = []
    for doc in documents:
        formatted.append(
            {
                "document.id": doc.get("id", ""),
                "document.content": doc.get("content", ""),
                "document.score": doc.get("score"),
                "document.metadata": serialize_json_data(doc.get("metadata", {})),
            }
        )
    return formatted


def format_input_messages(process_data: dict[str, Any]) -> str:
    """Format input messages from LLM process data."""
    prompts = process_data.get("prompts", [])
    if not prompts:
        return ""

    messages = []
    for prompt in prompts:
        if isinstance(prompt, dict):
            messages.append({
                "role": prompt.get("role", "user"),
                "content": prompt.get("text", prompt.get("content", "")),
            })
        elif isinstance(prompt, str):
            messages.append({
                "role": "user", 
                "content": prompt,
            })
    return serialize_json_data(messages)


def format_output_messages(outputs: dict[str, Any]) -> str:
    """Format output messages from LLM outputs."""
    text = outputs.get("text", "")
    if text:
        return serialize_json_data([{"role": "assistant", "content": text}])
    return ""
