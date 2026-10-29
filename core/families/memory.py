"""Validate memory payloads without I/O or disclosure decisions.

校验 memory 内容，不执行读写或披露决策。
"""

from __future__ import annotations

from typing import Any

LEVELS = ("fact", "scene", "detail", "impression")
SHAPES = ("point", "span", "pattern", "rule")
CHRONOS = ("once", "periodic", "annual")
ABOUTS = ("self", "other", "relation", "world")


def _need(payload: dict[str, Any], key: str) -> str:
    if key not in payload:
        raise ValueError(f"memory 缺少必填字段：{key}")
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"memory 字段 {key} 必须是非空字符串")
    return value


def validate(payload: dict[str, Any]) -> None:
    """Validate memory text, level and supported optional fields; invalid payload raises ValueError.

    校验记忆文本、层级及受支持可选字段，无效内容抛出 ValueError。
    """
    _need(payload, "text")
    level = _need(payload, "level")
    if level not in LEVELS:
        raise ValueError(f"memory.level 必须是 {'|'.join(LEVELS)}，收到 {level!r}")

    for key, allowed in (
        ("shape", SHAPES),
        ("chrono", CHRONOS),
        ("about", ABOUTS),
    ):
        if key not in payload:
            continue
        value = payload[key]
        if value not in allowed:
            raise ValueError(f"memory.{key} 必须是 {'|'.join(allowed)}，收到 {value!r}")

    first = payload.get("first")
    if first is not None and not isinstance(first, bool):
        raise ValueError("memory.first 必须是 bool")
