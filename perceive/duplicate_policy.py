"""Apply existing literal duplicate rules within the supplied identity boundary.

在给定身份范围内应用既有字面去重规则，不调用模型或执行读写。
"""
from __future__ import annotations

import re

def _normalize(text: str) -> str:
    """Build the existing punctuation/whitespace-free comparison key / 构造既有去标点及空白的比较键。"""
    return re.sub(r"[\s\W_]+", "", text).lower()


def _is_duplicate(key: str, other: str) -> bool:
    """Apply the existing equality or minimum-length containment rule / 应用既有相等或最短长度包含规则。"""
    if not key or not other:
        return False
    if key == other:
        return True
    short, long = sorted((key, other), key=len)
    return len(short) >= 4 and short in long


def filter_duplicates(
    items: list[dict],
    existing_texts: list[str] | None = None,
    *,
    existing_by_subject: dict[str, list[str]] | None = None,
    subject_of=None,
) -> list[dict]:
    """Deduplicate within supplied subject/scope identity or legacy global mode / 在给定主体及范围身份内去重，或使用旧的全局模式。"""
    scoped = existing_by_subject is not None and subject_of is not None
    seen_by_subject: dict[str, list[str]] = {}
    global_seen: list[str] = []

    def _keys(values: list[str]) -> list[str]:
        out: list[str] = []
        for raw in values:
            if isinstance(raw, str):
                key = _normalize(raw)
                if key:
                    out.append(key)
        return out

    if scoped:
        for boundary, values in (existing_by_subject or {}).items():
            seen_by_subject[str(boundary)] = _keys(values)
    else:
        global_seen = _keys(existing_texts or [])

    kept: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = item.get("text")
        if not isinstance(text, str):
            continue
        key = _normalize(text)
        if not key:
            continue
        if scoped:
            boundary = str(subject_of(item))
            seen = seen_by_subject.setdefault(boundary, [])
        else:
            seen = global_seen
        if any(_is_duplicate(key, old) for old in seen):
            continue
        seen.append(key)
        kept.append(item)
    return kept
