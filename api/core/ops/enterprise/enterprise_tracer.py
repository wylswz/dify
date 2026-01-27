"""
Enterprise OTLP tracing implementation.

Key difference from other tracers: uses BaseTraceInfo.trace_id as the OTLP trace_id
instead of conversation_id or workflow_run_id for consistent external trace correlation.
"""

import logging
from collections.abc import Sequence

from opentelemetry.trace import SpanKind
from sqlalchemy.orm import sessionmaker

from configs import dify_config
from core.ops.base_trace_instance import BaseTraceInstance
from core.ops.enterprise.client import (
    EnterpriseTraceClient,
    convert_datetime_to_nanoseconds,
    convert_hex_trace_id_to_int,
    convert_to_span_id,
    convert_to_trace_id,
    generate_span_id,
)
from core.ops.enterprise.entities.enterprise_trace_entity import SpanData, TraceMetadata
from core.ops.enterprise.entities.semconv import (
    DIFY_APP_ID,
    DIFY_CONVERSATION_ID,
    DIFY_MESSAGE_ID,
    DIFY_TENANT_ID,
    DIFY_TRACE_ID,
    DIFY_WORKFLOW_ID,
    DIFY_WORKFLOW_RUN_ID,
    GEN_AI_COMPLETION,
    GEN_AI_INPUT_MESSAGE,
    GEN_AI_OUTPUT_MESSAGE,
    GEN_AI_PROMPT,
    GEN_AI_PROVIDER_NAME,
    GEN_AI_REQUEST_MODEL,
    GEN_AI_RESPONSE_FINISH_REASON,
    GEN_AI_USAGE_INPUT_TOKENS,
    GEN_AI_USAGE_OUTPUT_TOKENS,
    GEN_AI_USAGE_TOTAL_TOKENS,
    RETRIEVAL_DOCUMENT,
    RETRIEVAL_QUERY,
    TOOL_DESCRIPTION,
    TOOL_NAME,
    TOOL_PARAMETERS,
    GenAISpanKind,
)
from core.ops.enterprise.utils import (
    create_common_span_attributes,
    create_links_from_trace_id,
    create_status_from_error,
    extract_retrieval_documents,
    format_input_messages,
    format_output_messages,
    format_retrieval_documents,
    get_user_id_from_message_data,
    get_workflow_node_status,
    serialize_json_data,
)
from core.ops.entities.trace_entity import (
    BaseTraceInfo,
    DatasetRetrievalTraceInfo,
    GenerateNameTraceInfo,
    MessageTraceInfo,
    ModerationTraceInfo,
    SuggestedQuestionTraceInfo,
    ToolTraceInfo,
    WorkflowTraceInfo,
)
from core.repositories import SQLAlchemyWorkflowNodeExecutionRepository
from core.workflow.entities import WorkflowNodeExecution
from core.workflow.enums import NodeType, WorkflowNodeExecutionMetadataKey
from extensions.ext_database import db
from models import WorkflowNodeExecutionTriggeredFrom

logger = logging.getLogger(__name__)


class EnterpriseTracer(BaseTraceInstance):
    """
    Enterprise OTLP trace implementation.

    This tracer uses BaseTraceInfo.trace_id as the OTLP trace_id for all spans,
    enabling correlation with external tracing systems that provide the trace_id.
    When trace_id is not provided, it falls back to generating a trace_id from
    workflow_run_id or message_id.
    """

    def __init__(self):
        self.trace_client = EnterpriseTraceClient(
            service_name=dify_config.ENTERPRISE_TRACE_SERVICE_NAME,
            endpoint=dify_config.ENTERPRISE_TRACE_ENDPOINT,
            token=dify_config.ENTERPRISE_TRACE_TOKEN,
        )

    def trace(self, trace_info: BaseTraceInfo) -> None:
        """Main tracing entry point - routes to appropriate trace handler."""
        logger.info("[Enterprise OTLP] Received trace info of type: %s", type(trace_info).__name__)
        if isinstance(trace_info, WorkflowTraceInfo):
            self.workflow_trace(trace_info)
        elif isinstance(trace_info, MessageTraceInfo):
            self.message_trace(trace_info)
        elif isinstance(trace_info, ModerationTraceInfo):
            # Moderation traces are typically not exported to external systems
            pass
        elif isinstance(trace_info, SuggestedQuestionTraceInfo):
            self.suggested_question_trace(trace_info)
        elif isinstance(trace_info, DatasetRetrievalTraceInfo):
            self.dataset_retrieval_trace(trace_info)
        elif isinstance(trace_info, ToolTraceInfo):
            self.tool_trace(trace_info)
        elif isinstance(trace_info, GenerateNameTraceInfo):
            # Generate name traces are typically not exported to external systems
            pass

    def api_check(self) -> bool:
        """Check if the OTLP endpoint is reachable."""
        return self.trace_client.api_check()

    def get_project_url(self) -> str:
        """Get the project URL."""
        return self.trace_client.get_project_url()

    def _get_trace_id(self, trace_info: BaseTraceInfo, fallback_id: str | None = None) -> int:
        """
        Get the trace ID from BaseTraceInfo.trace_id.

        This is the key difference from other tracers - we use the external trace_id
        provided in BaseTraceInfo.trace_id instead of generating one from conversation_id.

        Args:
            trace_info: The trace info containing the trace_id
            fallback_id: Fallback UUID to use if trace_id is not provided

        Returns:
            128-bit trace ID as integer
        """
        if trace_info.trace_id:
            try:
                return convert_hex_trace_id_to_int(trace_info.trace_id)
            except ValueError:
                logger.warning(
                    "Failed to convert trace_id '%s' to int, falling back to fallback_id", trace_info.trace_id
                )

        # Fallback to generating from fallback_id (workflow_run_id or message_id)
        if fallback_id:
            return convert_to_trace_id(fallback_id)

        raise ValueError("No trace_id or fallback_id provided")

    def workflow_trace(self, trace_info: WorkflowTraceInfo) -> None:
        """Handle workflow tracing using trace_id from BaseTraceInfo."""
        try:
            # Use BaseTraceInfo.trace_id as the OTLP trace_id
            trace_id = self._get_trace_id(trace_info, fallback_id=trace_info.workflow_run_id)
            workflow_span_id = convert_to_span_id(trace_info.workflow_run_id, "workflow")

            trace_metadata = TraceMetadata(
                trace_id=trace_id,
                workflow_span_id=workflow_span_id,
                session_id=trace_info.conversation_id or "",
                user_id=str(trace_info.metadata.get("user_id") or ""),
                links=create_links_from_trace_id(trace_info.trace_id) if not trace_info.trace_id else [],
                dify_trace_id=trace_info.trace_id,
            )

            self._add_workflow_span(trace_info, trace_metadata)

            # Process workflow node executions
            workflow_node_executions = self._get_workflow_node_executions(trace_info)
            for node_execution in workflow_node_executions:
                node_span = self._build_workflow_node_span(node_execution, trace_info, trace_metadata)
                if node_span:
                    self.trace_client.add_span(node_span)

                # Record LLM metrics for LLM nodes
                if node_execution.node_type == NodeType.LLM:
                    self._record_llm_metrics(node_execution)

            # Record workflow trace duration
            self._record_workflow_trace_duration(trace_info)

        except Exception:
            logger.exception("[Enterprise OTLP] Failed to process workflow trace")

    def message_trace(self, trace_info: MessageTraceInfo) -> None:
        """Handle message tracing using trace_id from BaseTraceInfo."""
        try:
            message_data = trace_info.message_data
            if message_data is None:
                return

            message_id = trace_info.message_id
            if not message_id:
                return

            # Use BaseTraceInfo.trace_id as the OTLP trace_id
            trace_id = self._get_trace_id(trace_info, fallback_id=message_id)
            user_id = get_user_id_from_message_data(message_data)
            status = create_status_from_error(trace_info.error)

            trace_metadata = TraceMetadata(
                trace_id=trace_id,
                workflow_span_id=0,
                session_id=trace_info.metadata.get("conversation_id") or "",
                user_id=user_id,
                links=[],
                dify_trace_id=trace_info.trace_id,
            )

            inputs_json = serialize_json_data(trace_info.inputs)
            outputs_str = str(trace_info.outputs)

            message_span_id = convert_to_span_id(message_id, "message")

            # Build common attributes with Dify-specific info
            common_attrs = create_common_span_attributes(
                session_id=trace_metadata.session_id,
                user_id=trace_metadata.user_id,
                span_kind=GenAISpanKind.CHAIN,
                inputs=inputs_json,
                outputs=outputs_str,
                dify_trace_id=trace_info.trace_id,
            )
            common_attrs.update(
                {
                    DIFY_MESSAGE_ID: message_id,
                    DIFY_CONVERSATION_ID: trace_info.metadata.get("conversation_id") or "",
                }
            )

            message_span = SpanData(
                trace_id=trace_metadata.trace_id,
                parent_span_id=None,
                span_id=message_span_id,
                name="message",
                start_time=convert_datetime_to_nanoseconds(trace_info.start_time),
                end_time=convert_datetime_to_nanoseconds(trace_info.end_time),
                attributes=common_attrs,
                status=status,
                links=trace_metadata.links,
                span_kind=SpanKind.SERVER,
            )
            self.trace_client.add_span(message_span)

            # Add LLM span as child
            llm_span = SpanData(
                trace_id=trace_metadata.trace_id,
                parent_span_id=message_span_id,
                span_id=convert_to_span_id(message_id, "llm"),
                name="llm",
                start_time=convert_datetime_to_nanoseconds(trace_info.start_time),
                end_time=convert_datetime_to_nanoseconds(trace_info.end_time),
                attributes={
                    **create_common_span_attributes(
                        session_id=trace_metadata.session_id,
                        user_id=trace_metadata.user_id,
                        span_kind=GenAISpanKind.LLM,
                        inputs=inputs_json,
                        outputs=outputs_str,
                        dify_trace_id=trace_info.trace_id,
                    ),
                    GEN_AI_REQUEST_MODEL: trace_info.metadata.get("ls_model_name") or "",
                    GEN_AI_PROVIDER_NAME: trace_info.metadata.get("ls_provider") or "",
                    GEN_AI_USAGE_INPUT_TOKENS: str(trace_info.message_tokens),
                    GEN_AI_USAGE_OUTPUT_TOKENS: str(trace_info.answer_tokens),
                    GEN_AI_USAGE_TOTAL_TOKENS: str(trace_info.total_tokens),
                    GEN_AI_PROMPT: inputs_json,
                    GEN_AI_COMPLETION: outputs_str,
                },
                status=status,
                links=trace_metadata.links,
            )
            self.trace_client.add_span(llm_span)

            # Record LLM metrics for message traces
            self._record_message_llm_metrics(trace_info)

            # Record message trace duration
            self._record_message_trace_duration(trace_info)

        except Exception:
            logger.exception("[Enterprise OTLP] Failed to process message trace")

    def dataset_retrieval_trace(self, trace_info: DatasetRetrievalTraceInfo) -> None:
        """Handle dataset retrieval tracing using trace_id from BaseTraceInfo."""
        try:
            if trace_info.message_data is None:
                return

            message_id = trace_info.message_id
            if not message_id:
                return

            # Use BaseTraceInfo.trace_id as the OTLP trace_id
            trace_id = self._get_trace_id(trace_info, fallback_id=message_id)

            trace_metadata = TraceMetadata(
                trace_id=trace_id,
                workflow_span_id=0,
                session_id=trace_info.metadata.get("conversation_id") or "",
                user_id=str(trace_info.metadata.get("user_id") or ""),
                links=[],
                dify_trace_id=trace_info.trace_id,
            )

            documents_data = extract_retrieval_documents(trace_info.documents)
            documents_json = serialize_json_data(documents_data)
            inputs_str = str(trace_info.inputs)

            dataset_retrieval_span = SpanData(
                trace_id=trace_metadata.trace_id,
                parent_span_id=convert_to_span_id(message_id, "message"),
                span_id=generate_span_id(),
                name="dataset_retrieval",
                start_time=convert_datetime_to_nanoseconds(trace_info.start_time),
                end_time=convert_datetime_to_nanoseconds(trace_info.end_time),
                attributes={
                    **create_common_span_attributes(
                        session_id=trace_metadata.session_id,
                        user_id=trace_metadata.user_id,
                        span_kind=GenAISpanKind.RETRIEVER,
                        inputs=inputs_str,
                        outputs=documents_json,
                        dify_trace_id=trace_info.trace_id,
                    ),
                    RETRIEVAL_QUERY: inputs_str,
                    RETRIEVAL_DOCUMENT: documents_json,
                },
                links=trace_metadata.links,
            )
            self.trace_client.add_span(dataset_retrieval_span)

        except Exception:
            logger.exception("[Enterprise OTLP] Failed to process dataset retrieval trace")

    def tool_trace(self, trace_info: ToolTraceInfo) -> None:
        """Handle tool tracing using trace_id from BaseTraceInfo."""
        try:
            if trace_info.message_data is None:
                return

            message_id = trace_info.message_id
            if not message_id:
                return

            # Use BaseTraceInfo.trace_id as the OTLP trace_id
            trace_id = self._get_trace_id(trace_info, fallback_id=message_id)
            status = create_status_from_error(trace_info.error)

            trace_metadata = TraceMetadata(
                trace_id=trace_id,
                workflow_span_id=0,
                session_id=trace_info.metadata.get("conversation_id") or "",
                user_id=str(trace_info.metadata.get("user_id") or ""),
                links=[],
                dify_trace_id=trace_info.trace_id,
            )

            tool_config_json = serialize_json_data(trace_info.tool_config)
            tool_inputs_json = serialize_json_data(trace_info.tool_inputs)
            inputs_json = serialize_json_data(trace_info.inputs)

            tool_span = SpanData(
                trace_id=trace_metadata.trace_id,
                parent_span_id=convert_to_span_id(message_id, "message"),
                span_id=generate_span_id(),
                name=trace_info.tool_name,
                start_time=convert_datetime_to_nanoseconds(trace_info.start_time),
                end_time=convert_datetime_to_nanoseconds(trace_info.end_time),
                attributes={
                    **create_common_span_attributes(
                        session_id=trace_metadata.session_id,
                        user_id=trace_metadata.user_id,
                        span_kind=GenAISpanKind.TOOL,
                        inputs=inputs_json,
                        outputs=str(trace_info.tool_outputs),
                        dify_trace_id=trace_info.trace_id,
                    ),
                    TOOL_NAME: trace_info.tool_name,
                    TOOL_DESCRIPTION: tool_config_json,
                    TOOL_PARAMETERS: tool_inputs_json,
                },
                status=status,
                links=trace_metadata.links,
            )
            self.trace_client.add_span(tool_span)

        except Exception:
            logger.exception("[Enterprise OTLP] Failed to process tool trace")

    def suggested_question_trace(self, trace_info: SuggestedQuestionTraceInfo) -> None:
        """Handle suggested question tracing using trace_id from BaseTraceInfo."""
        try:
            message_id = trace_info.message_id
            if not message_id:
                return

            # Use BaseTraceInfo.trace_id as the OTLP trace_id
            trace_id = self._get_trace_id(trace_info, fallback_id=message_id)
            status = create_status_from_error(trace_info.error)

            trace_metadata = TraceMetadata(
                trace_id=trace_id,
                workflow_span_id=0,
                session_id=trace_info.metadata.get("conversation_id") or "",
                user_id=str(trace_info.metadata.get("user_id") or ""),
                links=[],
                dify_trace_id=trace_info.trace_id,
            )

            inputs_json = serialize_json_data(trace_info.inputs)
            suggested_question_json = serialize_json_data(trace_info.suggested_question)

            suggested_question_span = SpanData(
                trace_id=trace_metadata.trace_id,
                parent_span_id=convert_to_span_id(message_id, "message"),
                span_id=convert_to_span_id(message_id, "suggested_question"),
                name="suggested_question",
                start_time=convert_datetime_to_nanoseconds(trace_info.start_time),
                end_time=convert_datetime_to_nanoseconds(trace_info.end_time),
                attributes={
                    **create_common_span_attributes(
                        session_id=trace_metadata.session_id,
                        user_id=trace_metadata.user_id,
                        span_kind=GenAISpanKind.LLM,
                        inputs=inputs_json,
                        outputs=suggested_question_json,
                        dify_trace_id=trace_info.trace_id,
                    ),
                    GEN_AI_REQUEST_MODEL: trace_info.metadata.get("ls_model_name") or "",
                    GEN_AI_PROVIDER_NAME: trace_info.metadata.get("ls_provider") or "",
                    GEN_AI_PROMPT: inputs_json,
                    GEN_AI_COMPLETION: suggested_question_json,
                },
                status=status,
                links=trace_metadata.links,
            )
            self.trace_client.add_span(suggested_question_span)

        except Exception:
            logger.exception("[Enterprise OTLP] Failed to process suggested question trace")

    def _add_workflow_span(self, trace_info: WorkflowTraceInfo, trace_metadata: TraceMetadata) -> None:
        """Add the main workflow span and optional message span."""
        message_span_id = None
        if trace_info.message_id:
            message_span_id = convert_to_span_id(trace_info.message_id, "message")

        status = create_status_from_error(trace_info.error)

        inputs_json = serialize_json_data(trace_info.workflow_run_inputs)
        outputs_json = serialize_json_data(trace_info.workflow_run_outputs)

        # Common Dify-specific attributes for workflow
        dify_attrs = {
            DIFY_TRACE_ID: trace_info.trace_id or "",
            DIFY_WORKFLOW_ID: trace_info.workflow_id,
            DIFY_WORKFLOW_RUN_ID: trace_info.workflow_run_id,
            DIFY_TENANT_ID: trace_info.tenant_id,
            DIFY_APP_ID: trace_info.metadata.get("app_id") or "",
        }
        if trace_info.conversation_id:
            dify_attrs[DIFY_CONVERSATION_ID] = trace_info.conversation_id

        # If there's a message_id, create a parent message span
        if message_span_id:
            message_span = SpanData(
                trace_id=trace_metadata.trace_id,
                parent_span_id=None,
                span_id=message_span_id,
                name="message",
                start_time=convert_datetime_to_nanoseconds(trace_info.start_time),
                end_time=convert_datetime_to_nanoseconds(trace_info.end_time),
                attributes={
                    **create_common_span_attributes(
                        session_id=trace_metadata.session_id,
                        user_id=trace_metadata.user_id,
                        span_kind=GenAISpanKind.CHAIN,
                        inputs=str(trace_info.workflow_run_inputs.get("sys.query") or ""),
                        outputs=outputs_json,
                        dify_trace_id=trace_info.trace_id,
                    ),
                    **dify_attrs,
                },
                status=status,
                links=trace_metadata.links,
                span_kind=SpanKind.SERVER,
            )
            self.trace_client.add_span(message_span)

        # Create the workflow span
        workflow_span = SpanData(
            trace_id=trace_metadata.trace_id,
            parent_span_id=message_span_id,
            span_id=trace_metadata.workflow_span_id,
            name="workflow",
            start_time=convert_datetime_to_nanoseconds(trace_info.start_time),
            end_time=convert_datetime_to_nanoseconds(trace_info.end_time),
            attributes={
                **create_common_span_attributes(
                    session_id=trace_metadata.session_id,
                    user_id=trace_metadata.user_id,
                    span_kind=GenAISpanKind.CHAIN,
                    inputs=inputs_json,
                    outputs=outputs_json,
                    dify_trace_id=trace_info.trace_id,
                ),
                **dify_attrs,
            },
            status=status,
            links=trace_metadata.links,
            span_kind=SpanKind.SERVER if message_span_id is None else SpanKind.INTERNAL,
        )
        self.trace_client.add_span(workflow_span)

    def _get_workflow_node_executions(self, trace_info: WorkflowTraceInfo) -> Sequence[WorkflowNodeExecution]:
        """Retrieve workflow node executions from database."""
        app_id = trace_info.metadata.get("app_id")
        if not app_id:
            raise ValueError("No app_id found in trace_info metadata")

        service_account = self.get_service_account_with_tenant(app_id)

        session_factory = sessionmaker(bind=db.engine)
        workflow_node_execution_repository = SQLAlchemyWorkflowNodeExecutionRepository(
            session_factory=session_factory,
            user=service_account,
            app_id=app_id,
            triggered_from=WorkflowNodeExecutionTriggeredFrom.WORKFLOW_RUN,
        )

        return workflow_node_execution_repository.get_by_workflow_run(workflow_run_id=trace_info.workflow_run_id)

    def _build_workflow_node_span(
        self, node_execution: WorkflowNodeExecution, trace_info: WorkflowTraceInfo, trace_metadata: TraceMetadata
    ) -> SpanData | None:
        """Build span for different workflow node types."""
        try:
            if node_execution.node_type == NodeType.LLM:
                return self._build_workflow_llm_span(trace_info, node_execution, trace_metadata)
            elif node_execution.node_type == NodeType.KNOWLEDGE_RETRIEVAL:
                return self._build_workflow_retrieval_span(trace_info, node_execution, trace_metadata)
            elif node_execution.node_type == NodeType.TOOL:
                return self._build_workflow_tool_span(trace_info, node_execution, trace_metadata)
            else:
                return self._build_workflow_task_span(trace_info, node_execution, trace_metadata)
        except Exception as e:
            logger.warning("[Enterprise OTLP] Error building span for node %s: %s", node_execution.id, e, exc_info=True)
            return None

    def _build_workflow_task_span(
        self, trace_info: WorkflowTraceInfo, node_execution: WorkflowNodeExecution, trace_metadata: TraceMetadata
    ) -> SpanData:
        """Build a generic task span for workflow nodes."""
        inputs_json = serialize_json_data(node_execution.inputs)
        outputs_json = serialize_json_data(node_execution.outputs)
        return SpanData(
            trace_id=trace_metadata.trace_id,
            parent_span_id=trace_metadata.workflow_span_id,
            span_id=convert_to_span_id(node_execution.id, "node"),
            name=node_execution.title,
            start_time=convert_datetime_to_nanoseconds(node_execution.created_at),
            end_time=convert_datetime_to_nanoseconds(node_execution.finished_at),
            attributes=create_common_span_attributes(
                session_id=trace_metadata.session_id,
                user_id=trace_metadata.user_id,
                span_kind=GenAISpanKind.TASK,
                inputs=inputs_json,
                outputs=outputs_json,
                dify_trace_id=trace_info.trace_id,
            ),
            status=get_workflow_node_status(node_execution),
            links=trace_metadata.links,
        )

    def _build_workflow_tool_span(
        self, trace_info: WorkflowTraceInfo, node_execution: WorkflowNodeExecution, trace_metadata: TraceMetadata
    ) -> SpanData:
        """Build a tool span for workflow tool nodes."""
        tool_des = {}
        if node_execution.metadata:
            tool_des = node_execution.metadata.get(WorkflowNodeExecutionMetadataKey.TOOL_INFO, {})

        inputs_json = serialize_json_data(node_execution.inputs or {})
        outputs_json = serialize_json_data(node_execution.outputs)

        return SpanData(
            trace_id=trace_metadata.trace_id,
            parent_span_id=trace_metadata.workflow_span_id,
            span_id=convert_to_span_id(node_execution.id, "node"),
            name=node_execution.title,
            start_time=convert_datetime_to_nanoseconds(node_execution.created_at),
            end_time=convert_datetime_to_nanoseconds(node_execution.finished_at),
            attributes={
                **create_common_span_attributes(
                    session_id=trace_metadata.session_id,
                    user_id=trace_metadata.user_id,
                    span_kind=GenAISpanKind.TOOL,
                    inputs=inputs_json,
                    outputs=outputs_json,
                    dify_trace_id=trace_info.trace_id,
                ),
                TOOL_NAME: node_execution.title,
                TOOL_DESCRIPTION: serialize_json_data(tool_des),
                TOOL_PARAMETERS: inputs_json,
            },
            status=get_workflow_node_status(node_execution),
            links=trace_metadata.links,
        )

    def _build_workflow_retrieval_span(
        self, trace_info: WorkflowTraceInfo, node_execution: WorkflowNodeExecution, trace_metadata: TraceMetadata
    ) -> SpanData:
        """Build a retrieval span for knowledge retrieval nodes."""
        input_value = str(node_execution.inputs.get("query", "")) if node_execution.inputs else ""
        output_value = serialize_json_data(node_execution.outputs.get("result", [])) if node_execution.outputs else ""

        retrieval_documents = node_execution.outputs.get("result", []) if node_execution.outputs else []
        semantic_retrieval_documents = format_retrieval_documents(retrieval_documents)
        semantic_retrieval_documents_json = serialize_json_data(semantic_retrieval_documents)

        return SpanData(
            trace_id=trace_metadata.trace_id,
            parent_span_id=trace_metadata.workflow_span_id,
            span_id=convert_to_span_id(node_execution.id, "node"),
            name=node_execution.title,
            start_time=convert_datetime_to_nanoseconds(node_execution.created_at),
            end_time=convert_datetime_to_nanoseconds(node_execution.finished_at),
            attributes={
                **create_common_span_attributes(
                    session_id=trace_metadata.session_id,
                    user_id=trace_metadata.user_id,
                    span_kind=GenAISpanKind.RETRIEVER,
                    inputs=input_value,
                    outputs=output_value,
                    dify_trace_id=trace_info.trace_id,
                ),
                RETRIEVAL_QUERY: input_value,
                RETRIEVAL_DOCUMENT: semantic_retrieval_documents_json,
            },
            status=get_workflow_node_status(node_execution),
            links=trace_metadata.links,
        )

    def _build_workflow_llm_span(
        self, trace_info: WorkflowTraceInfo, node_execution: WorkflowNodeExecution, trace_metadata: TraceMetadata
    ) -> SpanData:
        """Build an LLM span for LLM nodes."""
        process_data = node_execution.process_data or {}
        outputs = node_execution.outputs or {}
        usage_data = process_data.get("usage", {}) if "usage" in process_data else outputs.get("usage", {})

        prompts_json = serialize_json_data(process_data.get("prompts", []))
        text_output = str(outputs.get("text", ""))

        gen_ai_input_message = format_input_messages(process_data)
        gen_ai_output_message = format_output_messages(outputs)

        return SpanData(
            trace_id=trace_metadata.trace_id,
            parent_span_id=trace_metadata.workflow_span_id,
            span_id=convert_to_span_id(node_execution.id, "node"),
            name=node_execution.title,
            start_time=convert_datetime_to_nanoseconds(node_execution.created_at),
            end_time=convert_datetime_to_nanoseconds(node_execution.finished_at),
            attributes={
                **create_common_span_attributes(
                    session_id=trace_metadata.session_id,
                    user_id=trace_metadata.user_id,
                    span_kind=GenAISpanKind.LLM,
                    inputs=prompts_json,
                    outputs=text_output,
                    dify_trace_id=trace_info.trace_id,
                ),
                GEN_AI_REQUEST_MODEL: process_data.get("model_name") or "",
                GEN_AI_PROVIDER_NAME: process_data.get("model_provider") or "",
                GEN_AI_USAGE_INPUT_TOKENS: str(usage_data.get("prompt_tokens", 0)),
                GEN_AI_USAGE_OUTPUT_TOKENS: str(usage_data.get("completion_tokens", 0)),
                GEN_AI_USAGE_TOTAL_TOKENS: str(usage_data.get("total_tokens", 0)),
                GEN_AI_PROMPT: prompts_json,
                GEN_AI_COMPLETION: text_output,
                GEN_AI_RESPONSE_FINISH_REASON: outputs.get("finish_reason") or "",
                GEN_AI_INPUT_MESSAGE: gen_ai_input_message,
                GEN_AI_OUTPUT_MESSAGE: gen_ai_output_message,
            },
            status=get_workflow_node_status(node_execution),
            links=trace_metadata.links,
        )

    # Metrics recording methods
    def _record_llm_metrics(self, node_execution: WorkflowNodeExecution) -> None:
        """Record LLM performance metrics for workflow nodes."""
        try:
            process_data = node_execution.process_data or {}
            outputs = node_execution.outputs or {}
            usage = process_data.get("usage", {}) if "usage" in process_data else outputs.get("usage", {})

            model_provider = process_data.get("model_provider", "unknown")
            model_name = process_data.get("model_name", "unknown")
            model_mode = process_data.get("model_mode", "chat")

            # Record LLM duration
            latency_s = float(usage.get("latency", 0.0))
            if latency_s > 0:
                is_streaming = usage.get("time_to_first_token") is not None
                attributes = {
                    "gen_ai.system": model_provider,
                    "gen_ai.response.model": model_name,
                    "gen_ai.operation.name": model_mode,
                    "stream": "true" if is_streaming else "false",
                }
                self.trace_client.record_llm_duration(latency_s, attributes)

            # Record streaming metrics
            time_to_first_token = usage.get("time_to_first_token")
            if time_to_first_token is not None:
                ttft_seconds = float(time_to_first_token)
                if ttft_seconds > 0:
                    self.trace_client.record_time_to_first_token(
                        ttft_seconds=ttft_seconds, provider=model_provider, model=model_name, operation_name=model_mode
                    )

            time_to_generate = usage.get("time_to_generate")
            if time_to_generate is not None:
                ttg_seconds = float(time_to_generate)
                if ttg_seconds > 0:
                    self.trace_client.record_time_to_generate(
                        ttg_seconds=ttg_seconds, provider=model_provider, model=model_name, operation_name=model_mode
                    )

            # Record token usage
            input_tokens = int(usage.get("prompt_tokens", 0))
            output_tokens = int(usage.get("completion_tokens", 0))

            if input_tokens > 0:
                self.trace_client.record_token_usage(
                    token_count=input_tokens,
                    token_type="input",
                    operation_name=model_mode,
                    request_model=model_name,
                    response_model=model_name,
                    server_address=model_provider,
                    provider=model_provider,
                )

            if output_tokens > 0:
                self.trace_client.record_token_usage(
                    token_count=output_tokens,
                    token_type="output",
                    operation_name=model_mode,
                    request_model=model_name,
                    response_model=model_name,
                    server_address=model_provider,
                    provider=model_provider,
                )

        except Exception:
            logger.debug("[Enterprise OTLP] Failed to record LLM metrics")

    def _record_message_llm_metrics(self, trace_info: MessageTraceInfo) -> None:
        """Record LLM metrics for message traces."""
        try:
            trace_metadata = trace_info.metadata or {}
            message_data = trace_info.message_data or {}
            provider_latency = 0.0
            if isinstance(message_data, dict):
                provider_latency = float(message_data.get("provider_response_latency", 0.0) or 0.0)
            else:
                provider_latency = float(getattr(message_data, "provider_response_latency", 0.0) or 0.0)

            model_provider = trace_metadata.get("ls_provider") or (
                message_data.get("model_provider", "") if isinstance(message_data, dict) else ""
            )
            model_name = trace_metadata.get("ls_model_name") or (
                message_data.get("model_id", "") if isinstance(message_data, dict) else ""
            )

            # Record LLM duration
            if provider_latency > 0:
                is_streaming = trace_info.is_streaming_request
                duration_attributes = {
                    "gen_ai.system": model_provider,
                    "gen_ai.response.model": model_name,
                    "gen_ai.operation.name": "chat",
                    "stream": "true" if is_streaming else "false",
                }
                self.trace_client.record_llm_duration(provider_latency, duration_attributes)

            # Record streaming metrics
            if trace_info.is_streaming_request:
                if trace_info.gen_ai_server_time_to_first_token is not None:
                    ttft_seconds = float(trace_info.gen_ai_server_time_to_first_token)
                    if ttft_seconds > 0:
                        self.trace_client.record_time_to_first_token(
                            ttft_seconds=ttft_seconds, provider=str(model_provider or ""), model=str(model_name or "")
                        )

                if trace_info.llm_streaming_time_to_generate is not None:
                    ttg_seconds = float(trace_info.llm_streaming_time_to_generate)
                    if ttg_seconds > 0:
                        self.trace_client.record_time_to_generate(
                            ttg_seconds=ttg_seconds, provider=str(model_provider or ""), model=str(model_name or "")
                        )

            # Record token usage
            input_tokens = int(trace_info.message_tokens or 0)
            output_tokens = int(trace_info.answer_tokens or 0)

            if input_tokens > 0:
                self.trace_client.record_token_usage(
                    token_count=input_tokens,
                    token_type="input",
                    operation_name="chat",
                    request_model=str(model_name or ""),
                    response_model=str(model_name or ""),
                    server_address=str(model_provider or ""),
                    provider=str(model_provider or ""),
                )

            if output_tokens > 0:
                self.trace_client.record_token_usage(
                    token_count=output_tokens,
                    token_type="output",
                    operation_name="chat",
                    request_model=str(model_name or ""),
                    response_model=str(model_name or ""),
                    server_address=str(model_provider or ""),
                    provider=str(model_provider or ""),
                )

        except Exception:
            logger.debug("[Enterprise OTLP] Failed to record message LLM metrics")

    def _record_workflow_trace_duration(self, trace_info: WorkflowTraceInfo) -> None:
        """Record end-to-end workflow trace duration."""
        try:
            # Calculate duration from start_time and end_time
            if trace_info.start_time and trace_info.end_time:
                duration_s = (trace_info.end_time - trace_info.start_time).total_seconds()
            else:
                duration_s = float(trace_info.workflow_run_elapsed_time)

            if duration_s > 0:
                attributes = {
                    "conversation_mode": "workflow",
                    "workflow_status": trace_info.workflow_run_status,
                    "has_conversation": "true" if trace_info.conversation_id else "false",
                }
                self.trace_client.record_trace_duration(duration_s, attributes)

        except Exception:
            logger.debug("[Enterprise OTLP] Failed to record workflow trace duration")

    def _record_message_trace_duration(self, trace_info: MessageTraceInfo) -> None:
        """Record end-to-end message trace duration."""
        try:
            if trace_info.start_time and trace_info.end_time:
                duration = (trace_info.end_time - trace_info.start_time).total_seconds()

                if duration > 0:
                    attributes = {
                        "conversation_mode": trace_info.conversation_mode,
                        "stream": "true" if trace_info.is_streaming_request else "false",
                    }
                    self.trace_client.record_trace_duration(duration, attributes)

        except Exception:
            logger.debug("[Enterprise OTLP] Failed to record message trace duration")

    def __del__(self) -> None:
        """Ensure proper cleanup on garbage collection."""
        try:
            if hasattr(self, "trace_client"):
                self.trace_client.shutdown()
        except Exception:
            logger.exception("[Enterprise OTLP] Failed to shutdown trace client during cleanup")
