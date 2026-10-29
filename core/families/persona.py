"""Validate persona payloads without I/O or disclosure decisions.

校验 persona 内容，不执行读写或披露决策。
"""

from __future__ import annotations

from typing import Any


def validate(payload: dict[str, Any]) -> None:
    """Require nonempty persona text.

    要求非空人格文本。
    """
    if "text" not in payload:
        raise ValueError("persona 缺少必填字段：text")
    text = payload["text"]
    if not isinstance(text, str) or not text.strip():
        raise ValueError("persona.text 必须是非空字符串")
