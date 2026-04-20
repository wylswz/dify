"""Plugin/daemon callback: store async tool result and enqueue workflow resume."""

from __future__ import annotations

from typing import Any

from core.workflow.tool_interrupt_result_store import store_tool_interrupt_result
from tasks.app_generate.workflow_execute_task import resume_app_execution


def submit_tool_interrupt_result_and_resume(
    *,
    token: str,
    workflow_run_id: str,
    result: dict[str, Any],
) -> None:
    store_tool_interrupt_result(token=token, result=result)
    resume_app_execution.delay({"workflow_run_id": workflow_run_id})
