"""Tokenize supplied text into existing normalized character pairs without I/O.

将给定文本转换为既有规范字符二元组，不执行读写。
"""

from __future__ import annotations


def tokenize(text: str) -> list[str]:
    """Return existing normalized character pairs and preserve single characters / 返回既有规范字符二元组，保留单字符。"""
    chars = [char for char in str(text or "").lower() if char.isalnum()]
    if len(chars) == 1:
        return chars
    return [left + right for left, right in zip(chars, chars[1:])]
