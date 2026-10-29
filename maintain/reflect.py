"""Compute existing reflection signals without I/O; currently no production caller.

计算既有反思信号，不执行读写，目前没有生产调用方。
"""

from __future__ import annotations

import re

_NEGATIONS = (
    "不是这个意思",
    "没这么说",
    "我没说",
    "不是",
    "不对",
    "理解错了",
    "说错了",
)
# Remove question forms before checking explicit negation.
# 先排除疑问形式，再检查明确否定。
_QUESTION_FORMS = ("是不是", "对不对", "好不好", "行不行", "能不能", "要不要", "有没有")
_FOLLOWUPS = (
    "然后呢",
    "还有呢",
    "继续",
    "对啊",
    "对的",
    "没错",
    "然后",
    "还有",
    "嗯",
)
# Negation follows a boundary, with an optional short subject.
# 否定出现在边界之后，允许短主语。
_NEGATION_RE = re.compile(
    r"(?:^|[。！？!?；;，,、\s])"
    r"(?:我们|你们|他们|她们|我|你|他|她|它)?"
    r"(" + "|".join(re.escape(word) for word in _NEGATIONS) + r")"
)


def _bigrams(text: str) -> set[str]:
    """Compute existing punctuation-normalized pairs, preserving short input behavior / 计算既有去标点二元组，保留短输入行为。"""
    plain = re.sub(r"[^\w\u4e00-\u9fff]+", "", text or "").lower()
    if len(plain) < 2:
        return {plain} if plain else set()
    return {plain[i : i + 2] for i in range(len(plain) - 1)}


def _overlap(left: str, right: str) -> float:
    """Compute the existing module-specific pair overlap / 计算既有模块各自的二元组重合度。"""
    a, b = _bigrams(left), _bigrams(right)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _find_negation(text: str) -> str:
    """Find existing explicit negation after excluding question forms / 排除疑问形式后查找既有明确否定。"""
    cleaned = text
    for form in _QUESTION_FORMS:
        cleaned = cleaned.replace(form, "")
    match = _NEGATION_RE.search(cleaned)
    return match.group(1) if match else ""


def _find_followup(text: str) -> str:
    """Find existing follow-up cues after excluding negation text / 排除否定文本后查找既有接话线索。"""
    cleaned = text
    for word in _NEGATIONS:
        cleaned = cleaned.replace(word, "")
    for word in _FOLLOWUPS:
        if word in cleaned:
            return word
    return ""


def signals(prev_user: str, cur_user: str) -> dict:
    """Compute existing wrong/right reflection signals without modifying memory / 计算既有错误及正确反思信号，不修改记忆。"""
    prev = prev_user or ""
    cur = cur_user or ""
    wrong = 0
    right = 0
    reasons: list[str] = []

    negation = _find_negation(cur)
    if negation:
        wrong += 2
        reasons.append(f"明确否定（{negation}）")
    else:
        overlap = _overlap(prev, cur)
        if overlap > 0.6:
            wrong += 1
            reasons.append(f"重复解释同一件事（重合 {overlap:.2f}）")
        followup = _find_followup(cur)
        if followup:
            right += 1
            reasons.append(f"追问/展开（{followup}）")

    if prev and len(cur) < len(prev) * 0.5:
        wrong += 1
        reasons.append(f"回复骤短（{len(cur)} 字 / 上轮 {len(prev)} 字）")

    return {"wrong": wrong, "right": right, "reasons": reasons}


def should_reflect(result: dict) -> bool:
    """Apply the existing wrong-score threshold; invalid input returns false / 应用既有错误分阈值，无效输入返回否。"""
    try:
        return int(result.get("wrong", 0)) >= 2
    except (TypeError, ValueError, AttributeError):
        return False
