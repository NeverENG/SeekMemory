"""Validate media payloads without I/O or disclosure decisions.

校验 media 内容，不执行读写或披露决策。
"""

from __future__ import annotations

from typing import Any


def _need(payload: dict[str, Any], key: str) -> str:
    if key not in payload:
        raise ValueError(f"media 缺少必填字段：{key}")
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"media 字段 {key} 必须是非空字符串")
    return value


def validate(payload: dict[str, Any]) -> None:
    """Validate media type, title and URL with optional summary and sharer.

    校验媒体类型、标题和网址，概述及分享者可选。
    """
    _need(payload, "type")
    _need(payload, "title")
    _need(payload, "url")
    for key in ("summary", "shared_by"):
        if key not in payload:
            continue
        value = payload[key]
        if value is not None and not isinstance(value, str):
            raise ValueError(f"media.{key} 必须是字符串")
