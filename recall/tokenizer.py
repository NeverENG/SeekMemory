"""字符 bigram 分词；保留词频以供 BM25 计算。"""

from __future__ import annotations


def tokenize(text: str) -> list[str]:
    """返回规范化字符 bigram；单字符输入保留一个 token。"""
    chars = [char for char in str(text or "").lower() if char.isalnum()]
    if len(chars) == 1:
        return chars
    return [left + right for left, right in zip(chars, chars[1:])]
