from __future__ import annotations

import json
from collections.abc import Mapping
from typing import cast
from unittest.mock import MagicMock

from core.workflow.nodes.intent_executor.entities import INTENT_EXECUTOR_NODE_TYPE, IntentExecutorNodeData
from core.workflow.nodes.intent_executor.intent_executor_node import IntentExecutorNode
from core.workflow.nodes.intent_executor.invoker import IntentExecutorInvoker, IntentToolOutput, PreparedTool
from graphon.enums import WorkflowNodeExecutionMetadataKey, WorkflowNodeExecutionStatus
from graphon.file import File, FileTransferMethod, FileType
from graphon.model_runtime.entities.llm_entities import LLMResult, LLMUsage
from graphon.model_runtime.entities.message_entities import AssistantPromptMessage, PromptMessageTool
from graphon.node_events import NodeRunResult, StreamCompletedEvent
from graphon.runtime import GraphRuntimeState
from graphon.variables.segments import ArrayStringSegment, StringSegment
from tests.workflow_test_utils import build_test_graph_init_params, build_test_variable_pool

INTENTS_SELECTOR = ["src", "intents"]


def _prepared_tool(name: str) -> PreparedTool:
    return PreparedTool(
        name=name,
        provider_name="provider",
        prompt_tool=PromptMessageTool(name=name, description="desc", parameters={}),
        tool=MagicMock(),
    )


def _usage(*, total_tokens: int) -> LLMUsage:
    usage = LLMUsage.empty_usage()
    return usage.model_copy(update={"prompt_tokens": total_tokens, "total_tokens": total_tokens})


def _llm_result(
    *,
    text: str = "",
    tool_calls: list[AssistantPromptMessage.ToolCall] | None = None,
    total_tokens: int = 0,
) -> LLMResult:
    return LLMResult(
        model="model",
        message=AssistantPromptMessage(content=text, tool_calls=tool_calls or []),
        usage=_usage(total_tokens=total_tokens),
    )


def _tool_call(
    name: str, arguments: dict[str, object] | str, *, call_id: str = "call-1"
) -> AssistantPromptMessage.ToolCall:
    return AssistantPromptMessage.ToolCall(
        id=call_id,
        type="function",
        function=AssistantPromptMessage.ToolCall.ToolCallFunction(
            name=name,
            arguments=arguments if isinstance(arguments, str) else json.dumps(arguments),
        ),
    )


def _file(name: str = "out.txt") -> File:
    return File(
        file_type=FileType.DOCUMENT,
        transfer_method=FileTransferMethod.TOOL_FILE,
        related_id=f"file-{name}",
        filename=name,
        extension=".txt",
        mime_type="text/plain",
        size=1,
    )


class _StubInvoker:
    def __init__(
        self,
        *,
        supports_tool_call: bool = True,
        prepared_tools: list[PreparedTool] | None = None,
        plans: dict[str, LLMResult | Exception] | None = None,
        tool_outputs: dict[str, IntentToolOutput | Exception] | None = None,
        prepare_error: Exception | None = None,
    ) -> None:
        self._supports_tool_call = supports_tool_call
        self._prepared_tools = [_prepared_tool("tool_a")] if prepared_tools is None else prepared_tools
        self._plans = plans or {}
        self._tool_outputs = tool_outputs or {}
        self._prepare_error = prepare_error
        self.invocations: list[tuple[str, dict[str, object], int, str | None]] = []
        self.plan_calls: list[dict[str, object]] = []
        self.prepare_calls: list[object] = []

    def supports_tool_call(self) -> bool:
        return self._supports_tool_call

    def prepare_tools(self, *, tools: object, variable_pool: object) -> list[PreparedTool]:
        self.prepare_calls.append((tools, variable_pool))
        if self._prepare_error is not None:
            raise self._prepare_error
        return self._prepared_tools

    def plan(self, *, instruction: str, intent: str, tools: object) -> LLMResult:
        self.plan_calls.append({"instruction": instruction, "intent": intent, "tools": tools})
        outcome = self._plans[intent]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def invoke_tool(
        self,
        *,
        tool: PreparedTool,
        arguments: Mapping[str, object],
        workflow_call_depth: int,
        conversation_id: str | None,
    ) -> IntentToolOutput:
        self.invocations.append((tool.name, dict(arguments), workflow_call_depth, conversation_id))
        outcome = self._tool_outputs.get(tool.name)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome if outcome is not None else IntentToolOutput(text="")


def _build_node(*, invoker: _StubInvoker, intents_value: object = None, **data_overrides: object) -> IntentExecutorNode:
    data: dict[str, object] = {
        "type": INTENT_EXECUTOR_NODE_TYPE,
        "title": "Intent Executor",
        "model": {"provider": "provider", "name": "model", "mode": "chat"},
        "instruction": "be helpful",
        "intents": INTENTS_SELECTOR,
        "tools": [{"provider_name": "provider", "tool_name": "tool_a"}],
    }
    data.update(data_overrides)
    node_data = IntentExecutorNodeData.model_validate(data)

    variable_pool = build_test_variable_pool()
    if intents_value is not None:
        variable_pool.add(INTENTS_SELECTOR, intents_value)
    graph_runtime_state = GraphRuntimeState(variable_pool=variable_pool, start_at=0.0)

    return IntentExecutorNode(
        node_id="intent-executor-node",
        data=node_data,
        graph_init_params=build_test_graph_init_params(),
        graph_runtime_state=graph_runtime_state,
        invoker=cast(IntentExecutorInvoker, invoker),
    )


def _run(node: IntentExecutorNode) -> NodeRunResult:
    events = list(node._run())
    assert len(events) == 1
    event = events[0]
    assert isinstance(event, StreamCompletedEvent)
    return event.node_run_result


def test_two_intents_keep_input_order_and_aggregate_outputs() -> None:
    produced_file = _file()
    invoker = _StubInvoker(
        plans={
            "do-a": _llm_result(
                text="planning a",
                tool_calls=[_tool_call("tool_a", {"q": 1})],
                total_tokens=10,
            ),
            "do-b": _llm_result(
                text="planning b",
                tool_calls=[_tool_call("tool_a", {"q": 2})],
                total_tokens=20,
            ),
        },
        tool_outputs={"tool_a": IntentToolOutput(text="tool out", json=[{"k": "v"}], files=[produced_file])},
    )
    node = _build_node(invoker=invoker, intents_value=ArrayStringSegment(value=["do-a", "do-b"]))

    result = _run(node)

    assert result.status == WorkflowNodeExecutionStatus.SUCCEEDED
    assert result.inputs == {"intents": ["do-a", "do-b"]}

    results = result.outputs["results"].value
    assert [item["intent"] for item in results] == ["do-a", "do-b"]
    first = results[0]
    assert first["text"] == "planning a"
    assert first["error"] is None
    assert first["tool_calls"] == [
        {
            "id": "call-1",
            "name": "tool_a",
            "arguments": {"q": 1},
            "output": "tool out",
            "json": [{"k": "v"}],
            "error": None,
        }
    ]

    assert result.outputs["files"].value == [produced_file, produced_file]
    assert result.llm_usage.total_tokens == 30
    assert result.metadata[WorkflowNodeExecutionMetadataKey.TOTAL_TOKENS] == 30
    assert "usage" in result.outputs

    assert result.process_data["model_provider"] == "provider"
    assert result.process_data["model_name"] == "model"
    assert result.process_data["tools"] == ["tool_a"]
    assert result.process_data["instruction"] == "be helpful"


def test_no_tool_call_records_error_and_node_succeeds() -> None:
    invoker = _StubInvoker(plans={"intent": _llm_result(text="just text")})
    node = _build_node(invoker=invoker, intents_value=ArrayStringSegment(value=["intent"]))

    result = _run(node)

    assert result.status == WorkflowNodeExecutionStatus.SUCCEEDED
    item = result.outputs["results"].value[0]
    assert item["error"] == "Model returned no tool call"
    assert item["text"] == "just text"
    assert item["tool_calls"] == []


def test_tool_failure_does_not_stop_later_tool_calls_in_same_intent() -> None:
    invoker = _StubInvoker(
        prepared_tools=[_prepared_tool("failing"), _prepared_tool("succeeding")],
        plans={
            "intent": _llm_result(
                tool_calls=[
                    _tool_call("failing", {}, call_id="c1"),
                    _tool_call("succeeding", {}, call_id="c2"),
                ]
            )
        },
        tool_outputs={
            "failing": RuntimeError("boom"),
            "succeeding": IntentToolOutput(text="ok"),
        },
    )
    node = _build_node(invoker=invoker, intents_value=ArrayStringSegment(value=["intent"]))

    result = _run(node)

    assert result.status == WorkflowNodeExecutionStatus.SUCCEEDED
    calls = result.outputs["results"].value[0]["tool_calls"]
    assert calls[0]["error"] == "boom"
    assert calls[1]["error"] is None
    assert calls[1]["output"] == "ok"
    assert invoker.invocations == [("failing", {}, 0, None), ("succeeding", {}, 0, None)]


def test_unknown_tool_name_records_call_error() -> None:
    invoker = _StubInvoker(
        prepared_tools=[_prepared_tool("known")],
        plans={"intent": _llm_result(tool_calls=[_tool_call("missing", {})])},
    )
    node = _build_node(invoker=invoker, intents_value=ArrayStringSegment(value=["intent"]))

    result = _run(node)

    assert result.status == WorkflowNodeExecutionStatus.SUCCEEDED
    call = result.outputs["results"].value[0]["tool_calls"][0]
    assert call["name"] == "missing"
    assert call["error"] == "Unknown tool: missing"
    assert invoker.invocations == []


def test_plan_failure_is_scoped_to_its_intent() -> None:
    invoker = _StubInvoker(
        plans={
            "bad": RuntimeError("model exploded"),
            "good": _llm_result(text="fine", tool_calls=[_tool_call("tool_a", {})]),
        },
        tool_outputs={"tool_a": IntentToolOutput(text="done")},
    )
    node = _build_node(invoker=invoker, intents_value=ArrayStringSegment(value=["bad", "good"]))

    result = _run(node)

    assert result.status == WorkflowNodeExecutionStatus.SUCCEEDED
    results = result.outputs["results"].value
    assert results[0]["intent"] == "bad"
    assert results[0]["error"] == "model exploded"
    assert results[1]["intent"] == "good"
    assert results[1]["error"] is None
    assert results[1]["tool_calls"][0]["output"] == "done"


def test_empty_intent_list_succeeds_with_empty_results() -> None:
    invoker = _StubInvoker(supports_tool_call=False, prepared_tools=[])
    node = _build_node(invoker=invoker, intents_value=ArrayStringSegment(value=[]))

    result = _run(node)

    assert result.status == WorkflowNodeExecutionStatus.SUCCEEDED
    assert result.outputs["results"] == []


def test_string_segment_intent_produces_single_result() -> None:
    invoker = _StubInvoker(plans={"single": _llm_result(text="hi")})
    node = _build_node(invoker=invoker, intents_value=StringSegment(value="single"))

    result = _run(node)

    assert result.status == WorkflowNodeExecutionStatus.SUCCEEDED
    results = result.outputs["results"].value
    assert len(results) == 1
    assert results[0]["intent"] == "single"
    assert results[0]["error"] == "Model returned no tool call"


def test_missing_intents_variable_fails() -> None:
    node = _build_node(invoker=_StubInvoker(), intents_value=None)

    result = _run(node)

    assert result.status == WorkflowNodeExecutionStatus.FAILED
    assert "Intents variable" in result.error


def test_non_string_intents_variable_fails() -> None:
    node = _build_node(invoker=_StubInvoker(), intents_value=123)

    result = _run(node)

    assert result.status == WorkflowNodeExecutionStatus.FAILED
    assert "Intents variable" in result.error


def test_no_enabled_tools_fails() -> None:
    invoker = _StubInvoker(prepared_tools=[])
    node = _build_node(invoker=invoker, intents_value=ArrayStringSegment(value=["intent"]))

    result = _run(node)

    assert result.status == WorkflowNodeExecutionStatus.FAILED
    assert result.error == "No enabled tools."


def test_model_without_tool_call_feature_fails() -> None:
    invoker = _StubInvoker(supports_tool_call=False)
    node = _build_node(invoker=invoker, intents_value=ArrayStringSegment(value=["intent"]))

    result = _run(node)

    assert result.status == WorkflowNodeExecutionStatus.FAILED
    assert "tool call" in result.error


def test_prepare_tools_error_fails_node() -> None:
    invoker = _StubInvoker(prepare_error=RuntimeError("cannot build runtime"))
    node = _build_node(invoker=invoker, intents_value=ArrayStringSegment(value=["intent"]))

    result = _run(node)

    assert result.status == WorkflowNodeExecutionStatus.FAILED
    assert result.error == "cannot build runtime"


def test_invalid_json_arguments_record_call_error() -> None:
    invoker = _StubInvoker(
        plans={"intent": _llm_result(tool_calls=[_tool_call("tool_a", "{not json")])},
    )
    node = _build_node(invoker=invoker, intents_value=ArrayStringSegment(value=["intent"]))

    result = _run(node)

    assert result.status == WorkflowNodeExecutionStatus.SUCCEEDED
    call = result.outputs["results"].value[0]["tool_calls"][0]
    assert call["error"]
    assert invoker.invocations == []


def test_variable_mapping_includes_intents_and_instruction_selectors() -> None:
    node_data = IntentExecutorNodeData.model_validate(
        {
            "type": INTENT_EXECUTOR_NODE_TYPE,
            "model": {"provider": "provider", "name": "model", "mode": "chat"},
            "instruction": "use {{#other_node.output#}} here",
            "intents": ["src", "intents"],
            "tools": [],
        }
    )

    mapping = IntentExecutorNode._extract_variable_selector_to_variable_mapping(
        graph_config={},
        node_id="ie-node",
        node_data=node_data,
    )

    assert mapping["ie-node.intents"] == ["src", "intents"]
    assert mapping["ie-node.#other_node.output#"] == ["other_node", "output"]
