"""Merge pending async tool results into the variable pool before graph resume."""

from __future__ import annotations

from typing import Any

from graphon.runtime.graph_runtime_state import GraphRuntimeState
from graphon.variables.segments import StringSegment

from core.workflow.tool_interrupt_result_store import pop_tool_interrupt_result


def apply_pending_tool_interrupt_results(graph_runtime_state: GraphRuntimeState) -> None:
    pool = graph_runtime_state.variable_pool
    for node_id in graph_runtime_state.get_paused_nodes():
        token = _interrupt_token_from_pool(pool, node_id)
        if not token:
            continue
        result = pop_tool_interrupt_result(token)
        if result is None:
            continue
        pool.add([node_id, "__interrupt_result__"], result)


def _interrupt_token_from_pool(pool: Any, node_id: str) -> str | None:
    segment = pool.get([node_id, "__interrupt_token__"])
    if segment is None:
        return None
    if isinstance(segment, StringSegment):
        return segment.text
    text = getattr(segment, "text", None)
    if isinstance(text, str):
        return text
    value = getattr(segment, "value", None)
    if isinstance(value, str):
        return value
    return None
