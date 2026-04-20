"""Redis-backed storage for async tool results keyed by interrupt token."""

from __future__ import annotations

import json
from typing import Any

from extensions.ext_redis import redis_client

_KEY_PREFIX = "tool_interrupt:result:"


def store_tool_interrupt_result(
    *,
    token: str,
    result: dict[str, Any],
    ttl_seconds: int = 86_400,
) -> None:
    redis_client.setex(_KEY_PREFIX + token, ttl_seconds, json.dumps(result, ensure_ascii=False))


def pop_tool_interrupt_result(token: str) -> dict[str, Any] | None:
    key = _KEY_PREFIX + token
    raw = redis_client.get(key)
    if raw is None:
        return None
    redis_client.delete(key)
    if isinstance(raw, bytes | bytearray):
        raw = raw.decode()
    return json.loads(raw)
