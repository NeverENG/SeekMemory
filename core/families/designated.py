"""Validate designated payloads without I/O or disclosure decisions.

校验 designated 内容，不执行读写或披露决策。
"""

from __future__ import annotations

from typing import Any


def _need(payload: dict[str, Any], key: str) -> str:
    if key not in payload:
        raise ValueError(f"designated 缺少必填字段：{key}")
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"designated 字段 {key} 必须是非空字符串")
    return value


def validate(payload: dict[str, Any]) -> None:
    """Validate designated text/trigger only; private-session delivery is checked by callers.

    仅校验指定内容及触发词，私聊交付由调用方检查。
    """
    _need(payload, "text")
    _need(payload, "trigger")
    given = payload.get("given")
    if given is not None and not isinstance(given, (bool, str)):
        raise ValueError("designated.given 必须是 bool 或时间字符串")
    owner = payload.get("owner")
    if owner is not None and not isinstance(owner, str):
        raise ValueError("designated.owner 必须是字符串")
