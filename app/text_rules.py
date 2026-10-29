"""Shared proven-equivalent text rules; variants retain their existing semantics.

共享已证明等价的文本规则，各变体保留原有语义；不调用外部资源或执行读写。
"""
from __future__ import annotations

import re

_PUNCT = str.maketrans(
    "", "",
    " \t\r\n，。！？；：、,.!?;:'\"()[]{}<>…—-_/\\·“”‘’（）《》【】「」『』",
)


def alphanumeric_bigrams(text: str) -> set[str]:
    """Normalize alphanumeric character pairs, preserving one-character input / 规范化字母数字二元组，保留单字符输入。"""
    # Fast-path alphanumeric text, then translate known punctuation before filtering.
    # 字母数字文本直接处理，否则先移除已知标点再逐字符筛选。
    chars = str(text).lower()
    if not chars.isalnum():
        chars = chars.translate(_PUNCT)
        if not chars.isalnum():
            chars = "".join(c for c in chars if c.isalnum())
    if len(chars) < 2:
        return set(chars)
    return {a + b for a, b in zip(chars, chars[1:])}


def word_bigrams(text: str) -> set[str]:
    """Compute existing punctuation-normalized pairs, preserving short input behavior / 计算既有去标点二元组，保留短输入行为。"""
    plain = re.sub(r"[^\w\u4e00-\u9fff]+", "", text or "").lower()
    if len(plain) < 2:
        return {plain} if plain else set()
    return {plain[i : i + 2] for i in range(len(plain) - 1)}


def word_jaccard(left: str, right: str) -> float:
    """Compute existing character-pair Jaccard similarity / 计算既有字符二元组 Jaccard 相似度。"""
    a, b = word_bigrams(left), word_bigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


