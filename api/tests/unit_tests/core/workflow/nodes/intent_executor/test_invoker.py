from __future__ import annotations

from collections.abc import Generator, Iterable
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, Mock

import pytest

from core.app.entities.app_invoke_entities import DifyRunContext, InvokeFrom, UserFrom
from core.model_manager import ModelInstance
from core.tools.entities.tool_entities import ToolInvokeMessage
from core.workflow.nodes.intent_executor import invoker as invoker_module
from core.workflow.nodes.intent_executor.invoker import IntentExecutorInvoker, IntentToolOutput, PreparedTool
from graphon.file import File, FileTransferMethod, FileType
from graphon.model_runtime.entities.message_entities import PromptMessageTool
from graphon.model_runtime.entities.model_entities import ModelFeature


def _run_context() -> DifyRunContext:
    return DifyRunContext(
        tenant_id="tenant-id",
        app_id="app-id",
        user_id="user-id",
        user_from=UserFrom.ACCOUNT,
        invoke_from=InvokeFrom.DEBUGGER,
    )


def _prepared_tool() -> PreparedTool:
    return PreparedTool(
        name="tool_a",
        provider_name="provider",
        prompt_tool=PromptMessageTool(name="tool_a", description="desc", parameters={}),
        tool=MagicMock(),
    )


def _file() -> File:
    return File(
        file_type=FileType.DOCUMENT,
        transfer_method=FileTransferMethod.TOOL_FILE,
        related_id="file-1",
        filename="out.txt",
        extension=".txt",
        mime_type="text/plain",
        size=1,
    )


def _messages() -> Generator[ToolInvokeMessage, None, None]:
    yield ToolInvokeMessage(
        type=ToolInvokeMessage.MessageType.TEXT,
        message=ToolInvokeMessage.TextMessage(text="hello "),
    )
    yield ToolInvokeMessage(
        type=ToolInvokeMessage.MessageType.LINK,
        message=ToolInvokeMessage.TextMessage(text="http://example.com"),
    )
    yield ToolInvokeMessage(
        type=ToolInvokeMessage.MessageType.JSON,
        message=ToolInvokeMessage.JsonMessage(json_object={"k": "v"}),
    )
    yield ToolInvokeMessage(
        type=ToolInvokeMessage.MessageType.IMAGE_LINK,
        message=ToolInvokeMessage.TextMessage(text="/files/tools/file-1.png"),
        meta={"file": _file()},
    )
    yield ToolInvokeMessage(
        type=ToolInvokeMessage.MessageType.FILE,
        message=ToolInvokeMessage.TextMessage(text=""),
        meta={"file": _file()},
    )


def _patch_invoke(
    monkeypatch: pytest.MonkeyPatch, messages: Iterable[ToolInvokeMessage]
) -> tuple[MagicMock, MagicMock]:
    generic_invoke = MagicMock(return_value=messages)
    monkeypatch.setattr(
        invoker_module.ToolEngine,
        "generic_invoke",
        generic_invoke,
    )
    monkeypatch.setattr(
        invoker_module.ToolFileMessageTransformer,
        "transform_tool_invoke_messages",
        MagicMock(side_effect=lambda messages, **_kwargs: messages),
    )
    session = MagicMock()
    session_maker = MagicMock()
    session_maker.begin.return_value.__enter__ = MagicMock(return_value=session)
    session_maker.begin.return_value.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(
        invoker_module.session_factory,
        "get_session_maker",
        MagicMock(return_value=session_maker),
    )
    return session, generic_invoke


def test_invoke_tool_maps_messages_to_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_invoke(monkeypatch, _messages())
    invoker = IntentExecutorInvoker(
        run_context=_run_context(),
        model_instance=MagicMock(),
        request_metadata={"app_id": "app-id"},
    )

    output = invoker.invoke_tool(
        tool=_prepared_tool(),
        arguments={"q": 1},
        workflow_call_depth=0,
        conversation_id=None,
    )

    assert isinstance(output, IntentToolOutput)
    assert output.text == "hello http://example.com"
    assert output.json == [{"k": "v"}]
    assert len(output.files) == 2
    assert all(isinstance(f, File) for f in output.files)


def test_invoke_tool_passes_arguments_and_context(monkeypatch: pytest.MonkeyPatch) -> None:
    session, generic_invoke = _patch_invoke(monkeypatch, iter(()))
    invoker = IntentExecutorInvoker(
        run_context=_run_context(),
        model_instance=MagicMock(),
        request_metadata={"app_id": "app-id"},
    )
    prepared = _prepared_tool()

    invoker.invoke_tool(
        tool=prepared,
        arguments={"q": 1},
        workflow_call_depth=2,
        conversation_id="conversation-id",
    )

    kwargs = generic_invoke.call_args.kwargs
    assert kwargs["session"] is session
    # a forked runtime is invoked so the shared tool stays untouched across workers
    tool_mock = cast(MagicMock, prepared.tool)
    forked_tool = tool_mock.fork_tool_runtime.return_value
    tool_mock.fork_tool_runtime.assert_called_once_with(runtime=prepared.tool.runtime)
    assert kwargs["tool"] is forked_tool
    assert kwargs["tool_parameters"] == {"q": 1}
    assert kwargs["user_id"] == "user-id"
    assert kwargs["workflow_call_depth"] == 2
    assert kwargs["app_id"] == "app-id"
    assert kwargs["conversation_id"] == "conversation-id"


def test_invoke_tool_propagates_tool_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        invoker_module.ToolEngine,
        "generic_invoke",
        MagicMock(side_effect=RuntimeError("tool exploded")),
    )
    session_maker = MagicMock()
    session_maker.begin.return_value.__enter__ = MagicMock(return_value=MagicMock())
    session_maker.begin.return_value.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(
        invoker_module.session_factory,
        "get_session_maker",
        MagicMock(return_value=session_maker),
    )
    invoker = IntentExecutorInvoker(
        run_context=_run_context(),
        model_instance=MagicMock(),
        request_metadata={"app_id": "app-id"},
    )

    with pytest.raises(RuntimeError, match="tool exploded"):
        invoker.invoke_tool(
            tool=_prepared_tool(),
            arguments={},
            workflow_call_depth=0,
            conversation_id=None,
        )


@pytest.mark.parametrize(
    ("features", "expected"),
    [
        ([ModelFeature.TOOL_CALL], True),
        ([ModelFeature.MULTI_TOOL_CALL], True),
        ([ModelFeature.VISION], False),
        (None, False),
    ],
)
def test_supports_tool_call_checks_model_features(features: list[ModelFeature] | None, expected: bool) -> None:
    model_instance = cast(
        ModelInstance,
        SimpleNamespace(get_model_schema=Mock(return_value=SimpleNamespace(features=features))),
    )
    invoker = IntentExecutorInvoker(
        run_context=_run_context(),
        model_instance=model_instance,
        request_metadata={},
    )

    assert invoker.supports_tool_call() is expected
