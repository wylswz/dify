"""Intent-executor workflow node.

For each intent (a string) the node makes a single blocking function-calling
model call — system message from ``instruction``, user message from the intent —
and runs every returned tool call in order. Intents are independent and run in
parallel; per-intent and per-tool-call failures are recorded in the result and
the node still succeeds. Only setup failures (no enabled tools, model lacking
the tool-call feature, tool runtime build errors) fail the node.
"""

import json
import logging
from collections.abc import Generator, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, override

from context import capture_current_context
from core.workflow.system_variables import SystemVariableKey, get_system_text
from graphon.entities import GraphInitParams
from graphon.enums import WorkflowNodeExecutionMetadataKey, WorkflowNodeExecutionStatus
from graphon.file import File
from graphon.model_runtime.entities.llm_entities import LLMUsage
from graphon.model_runtime.utils.encoders import jsonable_encoder
from graphon.node_events import NodeEventBase, NodeRunResult, StreamCompletedEvent
from graphon.nodes.base import variable_template_parser
from graphon.nodes.base.node import Node
from graphon.variables.segments import ArrayFileSegment, ArrayObjectSegment, ArrayStringSegment, StringSegment
from graphon.variables.template_resolution import convert_template

from .entities import INTENT_EXECUTOR_NODE_TYPE, IntentExecutorNodeData
from .invoker import IntentExecutorInvoker, IntentToolOutput, PreparedTool

if TYPE_CHECKING:
    from graphon.runtime import GraphRuntimeState

logger = logging.getLogger(__name__)


class IntentExecutorNode(Node[IntentExecutorNodeData]):
    node_type = INTENT_EXECUTOR_NODE_TYPE

    def __init__(
        self,
        node_id: str,
        data: IntentExecutorNodeData,
        *,
        graph_init_params: "GraphInitParams",
        graph_runtime_state: "GraphRuntimeState",
        invoker: IntentExecutorInvoker,
    ) -> None:
        super().__init__(
            node_id=node_id,
            data=data,
            graph_init_params=graph_init_params,
            graph_runtime_state=graph_runtime_state,
        )
        self._invoker = invoker

    @classmethod
    @override
    def version(cls):
        return "1"

    @override
    def _run(self) -> Generator[NodeEventBase, None, None]:
        variable_pool = self.graph_runtime_state.variable_pool

        segment = variable_pool.get(self._node_data.intents)
        intents: list[str]
        match segment:
            case ArrayStringSegment():
                intents = [str(value) for value in segment.value]
            case StringSegment():
                intents = [segment.value]
            case _:
                yield StreamCompletedEvent(
                    node_run_result=self._failed_result(
                        error="Intents variable is missing or is not a string or array[string].",
                    )
                )
                return

        if not intents:
            yield StreamCompletedEvent(
                node_run_result=NodeRunResult(
                    status=WorkflowNodeExecutionStatus.SUCCEEDED,
                    inputs={"intents": []},
                    process_data=self._process_data(instruction=""),
                    outputs={"results": [], "files": []},
                )
            )
            return

        try:
            if not self._invoker.supports_tool_call():
                yield StreamCompletedEvent(
                    node_run_result=self._failed_result(
                        error="Model does not support tool call.",
                        inputs={"intents": intents},
                    )
                )
                return
            prepared_tools = self._invoker.prepare_tools(
                tools=self._node_data.tools,
                variable_pool=variable_pool,
            )
            if not prepared_tools:
                yield StreamCompletedEvent(
                    node_run_result=self._failed_result(
                        error="No enabled tools.",
                        inputs={"intents": intents},
                    )
                )
                return
        except Exception as exc:
            logger.warning("Intent executor node setup failed", exc_info=True)
            yield StreamCompletedEvent(
                node_run_result=self._failed_result(
                    error=str(exc),
                    error_type=type(exc).__name__,
                    inputs={"intents": intents},
                )
            )
            return

        instruction = convert_template(variable_pool, self._node_data.instruction).text
        conversation_id = get_system_text(variable_pool, SystemVariableKey.CONVERSATION_ID)
        workflow_call_depth = self.graph_init_params.call_depth

        execution_context = capture_current_context()
        max_workers = min(self._node_data.max_parallelism, len(intents))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            outcomes = list(
                pool.map(
                    lambda index: self._execute_intent(
                        intent=intents[index],
                        instruction=instruction,
                        prepared_tools=prepared_tools,
                        workflow_call_depth=workflow_call_depth,
                        conversation_id=conversation_id,
                        execution_context=execution_context,
                    ),
                    range(len(intents)),
                )
            )

        results = [outcome[0] for outcome in outcomes]
        files: list[File] = []
        usage = LLMUsage.empty_usage()
        for _, intent_usage, intent_files in outcomes:
            files.extend(intent_files)
            usage = usage + intent_usage

        yield StreamCompletedEvent(
            node_run_result=NodeRunResult(
                status=WorkflowNodeExecutionStatus.SUCCEEDED,
                inputs={"intents": intents},
                process_data=self._process_data(instruction=instruction, prepared_tools=prepared_tools),
                outputs={
                    "results": ArrayObjectSegment(value=results),
                    "files": ArrayFileSegment(value=files),
                    "usage": jsonable_encoder(usage),
                },
                metadata={
                    WorkflowNodeExecutionMetadataKey.TOTAL_TOKENS: usage.total_tokens,
                    WorkflowNodeExecutionMetadataKey.TOTAL_PRICE: usage.total_price,
                    WorkflowNodeExecutionMetadataKey.CURRENCY: usage.currency,
                },
                llm_usage=usage,
            )
        )

    def _execute_intent(
        self,
        *,
        intent: str,
        instruction: str,
        prepared_tools: Sequence[PreparedTool],
        workflow_call_depth: int,
        conversation_id: str | None,
        execution_context: Any,
    ) -> tuple[dict[str, Any], LLMUsage, list[File]]:
        with execution_context:
            result: dict[str, Any] = {"intent": intent, "text": "", "error": None, "tool_calls": []}
            files: list[File] = []
            usage = LLMUsage.empty_usage()

            try:
                llm_result = self._invoker.plan(
                    instruction=instruction,
                    intent=intent,
                    tools=[tool.prompt_tool for tool in prepared_tools],
                )
            except Exception as exc:
                result["error"] = str(exc)
                return result, usage, files

            if llm_result.usage is not None:
                usage = llm_result.usage
            message = llm_result.message
            result["text"] = message.content if isinstance(message.content, str) else ""

            if not message.tool_calls:
                result["error"] = "Model returned no tool call"
                return result, usage, files

            tools_by_name = {tool.name: tool for tool in prepared_tools}
            for tool_call in message.tool_calls:
                call: dict[str, Any] = {
                    "id": tool_call.id,
                    "name": tool_call.function.name,
                    "arguments": {},
                    "output": "",
                    "json": [],
                    "error": None,
                }
                result["tool_calls"].append(call)

                try:
                    arguments = json.loads(tool_call.function.arguments)
                    if not isinstance(arguments, dict):
                        raise ValueError("Tool call arguments must be a JSON object")
                except Exception as exc:
                    call["error"] = str(exc)
                    continue
                call["arguments"] = arguments

                prepared = tools_by_name.get(tool_call.function.name)
                if prepared is None:
                    call["error"] = f"Unknown tool: {tool_call.function.name}"
                    continue

                try:
                    output: IntentToolOutput = self._invoker.invoke_tool(
                        tool=prepared,
                        arguments=arguments,
                        workflow_call_depth=workflow_call_depth,
                        conversation_id=conversation_id,
                    )
                except Exception as exc:
                    call["error"] = str(exc)
                    continue
                call["output"] = output.text
                call["json"] = list(output.json)
                files.extend(output.files)

            return result, usage, files

    def _process_data(
        self,
        *,
        instruction: str,
        prepared_tools: Sequence[PreparedTool] | None = None,
    ) -> dict[str, Any]:
        return {
            "model_provider": self._node_data.model.provider,
            "model_name": self._node_data.model.name,
            "tools": [tool.name for tool in prepared_tools or []],
            "instruction": instruction,
        }

    def _failed_result(
        self,
        *,
        error: str,
        inputs: Mapping[str, Any] | None = None,
        error_type: str = "",
    ) -> NodeRunResult:
        return NodeRunResult(
            status=WorkflowNodeExecutionStatus.FAILED,
            inputs=inputs or {},
            error=error,
            error_type=error_type,
        )

    @classmethod
    @override
    def _extract_variable_selector_to_variable_mapping(
        cls,
        *,
        graph_config: Mapping[str, Any],
        node_id: str,
        node_data: IntentExecutorNodeData,
    ) -> Mapping[str, Sequence[str]]:
        _ = graph_config
        variable_mapping: dict[str, Sequence[str]] = {node_id + ".intents": node_data.intents}
        if node_data.instruction:
            for selector in variable_template_parser.extract_selectors_from_template(node_data.instruction):
                variable_mapping[node_id + "." + selector.variable] = selector.value_selector
        return variable_mapping
