"""Semantic conventions for Enterprise OTLP tracing."""

from enum import StrEnum
from typing import Final

# Service feature attribute
ENTERPRISE_SERVICE_FEATURE: Final[str] = "dify.enterprise.service.feature"

# Public attributes
GEN_AI_SESSION_ID: Final[str] = "gen_ai.session.id"
GEN_AI_USER_ID: Final[str] = "gen_ai.user.id"
GEN_AI_USER_NAME: Final[str] = "gen_ai.user.name"
GEN_AI_SPAN_KIND: Final[str] = "gen_ai.span.kind"
GEN_AI_FRAMEWORK: Final[str] = "gen_ai.framework"

# Chain attributes
INPUT_VALUE: Final[str] = "input.value"
OUTPUT_VALUE: Final[str] = "output.value"

# Retriever attributes
RETRIEVAL_QUERY: Final[str] = "retrieval.query"
RETRIEVAL_DOCUMENT: Final[str] = "retrieval.document"

# LLM attributes
GEN_AI_REQUEST_MODEL: Final[str] = "gen_ai.request.model"
GEN_AI_PROVIDER_NAME: Final[str] = "gen_ai.provider.name"
GEN_AI_USAGE_INPUT_TOKENS: Final[str] = "gen_ai.usage.input_tokens"
GEN_AI_USAGE_OUTPUT_TOKENS: Final[str] = "gen_ai.usage.output_tokens"
GEN_AI_USAGE_TOTAL_TOKENS: Final[str] = "gen_ai.usage.total_tokens"
GEN_AI_PROMPT: Final[str] = "gen_ai.prompt"
GEN_AI_COMPLETION: Final[str] = "gen_ai.completion"
GEN_AI_RESPONSE_FINISH_REASON: Final[str] = "gen_ai.response.finish_reason"

GEN_AI_INPUT_MESSAGE: Final[str] = "gen_ai.input.messages"
GEN_AI_OUTPUT_MESSAGE: Final[str] = "gen_ai.output.messages"

# Tool attributes
TOOL_NAME: Final[str] = "tool.name"
TOOL_DESCRIPTION: Final[str] = "tool.description"
TOOL_PARAMETERS: Final[str] = "tool.parameters"

# Dify specific attributes
DIFY_TRACE_ID: Final[str] = "dify.trace.id"
DIFY_WORKFLOW_ID: Final[str] = "dify.workflow.id"
DIFY_WORKFLOW_RUN_ID: Final[str] = "dify.workflow.run_id"
DIFY_APP_ID: Final[str] = "dify.app.id"
DIFY_TENANT_ID: Final[str] = "dify.tenant.id"
DIFY_CONVERSATION_ID: Final[str] = "dify.conversation.id"
DIFY_MESSAGE_ID: Final[str] = "dify.message.id"


class GenAISpanKind(StrEnum):
    CHAIN = "CHAIN"
    RETRIEVER = "RETRIEVER"
    RERANKER = "RERANKER"
    LLM = "LLM"
    EMBEDDING = "EMBEDDING"
    TOOL = "TOOL"
    AGENT = "AGENT"
    TASK = "TASK"
