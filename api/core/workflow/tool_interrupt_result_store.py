"""Redis-backed storage for async tool results keyed by interrupt token."""

from __future__ import annotations

import json
from typing import Any

from extensions.ext_redis import redis_client

_KEY_PREFIX = "tool_interrupt:result:"
_RUN_BINDING_PREFIX = "tool_interrupt:run:"


def store_tool_interrupt_result(
    *,
    token: str,
    result: dict[str, Any],
    ttl_seconds: int = 86_400,
) -> None:
    redis_client.setex(_KEY_PREFIX + token, ttl_seconds, json.dumps(result, ensure_ascii=False))


def store_tool_interrupt_run_binding(
    *,
    token: str,
    workflow_run_id: str,
    ttl_seconds: int = 86_400,
) -> None:
    """Map interrupt token to workflow run when the graph pauses (plugin never sees the run id)."""
    redis_client.setex(_RUN_BINDING_PREFIX + token, ttl_seconds, workflow_run_id)


def get_tool_interrupt_run_binding(token: str) -> str | None:
    key = _RUN_BINDING_PREFIX + token
    raw = redis_client.get(key)
    if raw is None:
        return None
    if isinstance(raw, bytes | bytearray):
        raw = raw.decode()
    return raw


def delete_tool_interrupt_run_binding(token: str) -> None:
    redis_client.delete(_RUN_BINDING_PREFIX + token)


def pop_tool_interrupt_result(token: str) -> dict[str, Any] | None:
    key = _KEY_PREFIX + token
    raw = redis_client.get(key)
    if raw is None:
        return None
    redis_client.delete(key)
    if isinstance(raw, bytes | bytearray):
        raw = raw.decode()
    return json.loads(raw)
