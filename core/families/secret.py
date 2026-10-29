"""Validate secret payloads without I/O or disclosure decisions.

校验 secret 内容，不执行读写或披露决策。
"""

from __future__ import annotations

from typing import Any


def _need(payload: dict[str, Any], key: str) -> str:
    if key not in payload:
        raise ValueError(f"secret 缺少必填字段：{key}")
    value = payload[key]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"secret 字段 {key} 必须是非空字符串")
    return value


def validate(payload: dict[str, Any]) -> None:
    """Validate the secret reference and shadow text; recall excludes the secret family.

    校验秘密引用及影子文本，召回排除 secret 类别。
    """
    _need(payload, "ref")
    _need(payload, "shadow_text")
    hint = payload.get("hint")
    if hint is not None and not isinstance(hint, str):
        raise ValueError("secret.hint 必须是字符串")
