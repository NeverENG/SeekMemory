"""Validate example payloads without I/O or disclosure decisions.

校验 example 内容，不执行读写或披露决策。
"""

from __future__ import annotations

from typing import Any


def _need(payload: dict[str, Any], key: str) -> str:
    if key not in payload:
        raise ValueError(f"example 缺少必填字段：{key}")
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"example 字段 {key} 必须是非空字符串")
    return value


def validate(payload: dict[str, Any]) -> None:
    """Validate one user/assistant style example with optional tags.

    校验一组用户及助手风格样例，标签可选。
    """
    _need(payload, "user")
    _need(payload, "assistant")
    tags = payload.get("tags")
    if tags is None:
        return
    if not isinstance(tags, (list, tuple)):
        raise ValueError("example.tags 必须是字符串列表")
    if not all(isinstance(tag, str) for tag in tags):
        raise ValueError("example.tags 必须全部是字符串")
