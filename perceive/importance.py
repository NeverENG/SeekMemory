"""Rank Dream topics with deterministic user and paired-assistant signals; no model calls or queue writes.

以确定性的用户及配对助手信号对夜间整理话题排序，不调用模型或写入队列。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

try:
    from ..app.contracts import DialogueTurn
except ImportError:
    from app.contracts import DialogueTurn

MIN_IMPORTANCE_SCORE = 2.0

# Each category scores once; reasons are labels, never bodies.
# 每个类别仅计分一次，原因仅为标记，不含正文。
_SIGNALS: tuple[tuple[str, float, re.Pattern[str]], ...] = (
    (
        "explicit_remember",
        4.0,
        re.compile(r"(?:\u8bb0\u4f4f|\u8bb0\u4e00\u4e0b|\u63d0\u9192|\u522b\u5fd8\u4e86|\u5907\u5fd8)"),
    ),
    (
        "identity_profile",
        3.0,
        re.compile(r"(?:\u6211\u53eb|\u540d\u5b57|\u6211\u662f|\u4f4f\u5728|\u8001\u5bb6|\u751f\u65e5|\u5e74\u9f84|\u804c\u4e1a|\u5de5\u4f5c|\u516c\u53f8|\u5b66\u6821|\u4e13\u4e1a|\u54ea\u91cc\u4eba)"),
    ),
    (
        "preference_boundary",
        3.0,
        re.compile(r"(?:\u559c\u6b22|\u8ba8\u538c|\u4e0d\u559c\u6b22|\u504f\u597d|\u7231\u5403|\u4e0d\u5403|\u5fcc\u53e3|\u8fc7\u654f|\u5bb3\u6015|\u53d7\u4e0d\u4e86|\u96f7\u533a|\u7981\u5fcc)"),
    ),
    (
        "relationship_family",
        3.0,
        re.compile(r"(?:\u5973\u670b\u53cb|\u7537\u670b\u53cb|\u8001\u5a46|\u8001\u516c|\u5bf9\u8c61|\u7238|\u5988|\u7236\u6bcd|\u5bb6\u4eba|\u5b69\u5b50|\u513f\u5b50|\u5973\u513f|\u670b\u53cb|\u95fa\u871c|\u5144\u5f1f|\u732b|\u72d7|\u5ba0\u7269)"),
    ),
    (
        "plan_commitment",
        3.0,
        re.compile(r"(?:\u8ba1\u5212|\u6253\u7b97|\u51c6\u5907|\u7ea6\u4e86|\u8981\u53bb|\u4e0b\u5468|\u660e\u5929|\u540e\u5929|\u5468\u672b|\u51fa\u5dee|\u65c5\u884c|\u9762\u8bd5|\u8003\u8bd5|\u7ed3\u5a5a|\u642c\u5bb6)"),
    ),
    (
        "privacy_boundary",
        4.0,
        re.compile(r"(?:\u4e0d\u8981\u544a\u8bc9|\u522b\u8bf4|\u79d8\u5bc6|\u4fdd\u5bc6|\u9690\u79c1|\u79c1\u4e8b|\u53ea\u544a\u8bc9\u4f60|\u4e0d\u80fd\u8ba9\u522b\u4eba\u77e5\u9053)"),
    ),
    (
        "significant_event",
        2.0,
        re.compile(r"(?:\u5165\u804c|\u79bb\u804c|\u8f9e\u804c|\u5347\u804c|\u52a0\u85aa|\u6bd5\u4e1a|\u5f00\u5b66|\u4f4f\u9662|\u624b\u672f|\u751f\u75c5|\u6000\u5b55|\u7ed3\u5a5a|\u79bb\u5a5a|\u5206\u624b|\u642c\u5bb6|\u51fa\u56fd|\u4e2d\u5956|\u53bb\u4e16)"),
    ),
    (
        "strong_emotion",
        1.0,
        re.compile(r"(?:\u5d29\u6e83|\u54ed|\u96be\u53d7|\u538b\u529b|\u7126\u8651|\u5931\u7720|\u751f\u6c14|\u59d4\u5c48|\u5f00\u5fc3|\u9ad8\u5174|\u96be\u8fc7|\u5bb3\u6015|\u70e6)"),
    ),
)


@dataclass(frozen=True)
class TopicImportance:
    """Hold a topics bounded score, reason labels and original rows / 保存话题的有上限分数、原因标记及原始行。"""
    session_id: str
    topic_id: str
    rows: tuple[DialogueTurn, ...]
    score: float
    reasons: tuple[str, ...]
    latest_at: str


def score_topic(rows: Iterable[DialogueTurn]) -> tuple[float, tuple[str, ...]]:
    """Score user signals and paired assistant behavior; assistant-only topics score zero / 给用户信号及配对助手行为打分，仅含助手的话题得零分。"""
    rows = list(rows)
    user_text = "\n".join(
        str(turn.text or "")
        for turn in rows
        if str(turn.role or "") == "user" and str(turn.text or "").strip()
    )
    assistant_text = "\n".join(
        str(turn.text or "")
        for turn in rows
        if str(turn.role or "") == "assistant" and str(turn.text or "").strip()
    )
    if not user_text:
        return 0.0, ()
    reasons: list[str] = []
    for label, _weight, pattern in _SIGNALS:
        if pattern.search(user_text):
            reasons.append(label)
    if _USER_CORRECTION.search(user_text):
        reasons.append("user_correction")
    if assistant_text and _ASSISTANT_BEHAVIOR.search(assistant_text):
        reasons.append("assistant_behavior")
    return _refine(user_text, tuple(reasons))


def _latest_at(rows: Iterable[DialogueTurn]) -> str:
    """Read the latest nonempty supplied timestamp label / 读取给定的最新非空时间标签。"""
    values = [str(turn.at or "") for turn in rows if str(turn.at or "").strip()]
    return max(values) if values else ""


def rank_topics(items: Iterable[DialogueTurn]) -> list[TopicImportance]:
    """Group by session/topic and rank with stable existing importance ordering / 按会话及话题分组，并按既有稳定重要性顺序排序。"""
    buckets: dict[tuple[str, str], list[DialogueTurn]] = {}
    order: list[tuple[str, str]] = []
    for turn in items:
        key = (str(turn.session_id or ""), str(turn.topic_id or ""))
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(turn)
    ranked = []
    for session_id, topic_id in order:
        rows = tuple(buckets[(session_id, topic_id)])
        score, reasons = score_topic(rows)
        ranked.append(
            TopicImportance(
                session_id,
                topic_id,
                rows,
                score,
                reasons,
                _latest_at(rows),
            )
        )
    ranked.sort(key=lambda item: (item.topic_id, item.session_id))
    ranked.sort(key=lambda item: item.latest_at, reverse=True)
    ranked.sort(key=lambda item: item.score, reverse=True)
    return ranked


def select_ranked_topics(
    ranked: Iterable[TopicImportance],
    cap: int,
    min_score: float = MIN_IMPORTANCE_SCORE,
) -> list[tuple[str, str, list[DialogueTurn]]]:
    """Select a bounded number of already-ranked eligible topics / 从已排序且符合条件的话题中限量选择。"""
    limit = max(0, int(cap))
    if limit <= 0:
        return []
    return [
        (item.session_id, item.topic_id, list(item.rows))
        for item in ranked
        if item.score >= float(min_score)
    ][:limit]


def select_important_topics(
    items: Iterable[DialogueTurn],
    cap: int,
    min_score: float = MIN_IMPORTANCE_SCORE,
) -> list[tuple[str, str, list[DialogueTurn]]]:
    """Rank then select bounded high-importance topic groups / 排序后限量选择高重要性话题组。"""
    return select_ranked_topics(rank_topics(items), cap, min_score)

_WEIGHTS = {
    **{label: weight for label, weight, _pattern in _SIGNALS},
    "user_correction": 4.0,
    "assistant_behavior": 3.0,
}
_USER_CORRECTION = re.compile(
    r"(?:\u4f60\u9519\u4e86|\u4e0d\u662f\u8fd9\u6837|\u4f60\u7406\u89e3\u9519|"
    r"\u7b54\u975e\u6240\u95ee|\u8bf4\u5f97\u4e0d\u5bf9|\u4e0d\u662f\u8fd9\u4e2a\u610f\u601d|"
    r"\u4f60\u641e\u9519|\u7ea0\u6b63\u4e00\u4e0b|\u6211\u8bf4\u7684\u662f|\u521a\u624d\u4e0d\u662f)"
)

_ASSISTANT_BEHAVIOR = re.compile(
    "|".join((
        r"\u6211\u5728\uff0c",
        r"\u6211\u5728\u3002",
        r"\u6211\u5728\uff01",
        r"\u6211\u5728\u542c",
        r"\u522b\u96be\u8fc7",
        r"\u62b1\u62b1",
        r"\u8f9b\u82e6\u4e86",
        r"\u7406\u89e3\u4f60",
        r"\u966a\u7740\u4f60",
        r"\u542c\u4f60\u8bf4",
        r"\u522b\u6015",
        r"\u4f1a\u597d\u7684",
        r"\u4e0d\u5bb9\u6613",
        r"\u5bf9\u4e0d\u8d77",
        r"\u62b1\u6b49",
        r"\u6211\u9519\u4e86",
        r"\u8bf4\u9519\u4e86",
        r"\u521a\u624d\u8bf4\u9519",
        r"\u66f4\u6b63",
        r"\u7ea0\u6b63",
        r"\u6211\u7406\u89e3\u9519",
        r"\u4e0d\u786e\u5b9a",
        r"\u65e0\u6cd5\u786e\u8ba4",
        r"\u9700\u8981\u6838\u5b9e",
        r"\u6211\u4e0d\u6e05\u695a",
        r"\u8ba9\u6211\u786e\u8ba4",
        r"\u6211\u5f97\u67e5\u4e00\u4e0b",
        r"\u4e0d\u80fd\u8bf4",
        r"\u4e0d\u65b9\u4fbf\u8bf4",
        r"\u6d89\u53ca\u9690\u79c1",
        r"\u4fdd\u5bc6",
        r"\u4e0d\u4f1a\u900f\u9732",
        r"\u4e0d\u4f20\u64ad",
        r"\u4f60\u662f\u6307",
        r"\u4f60\u8bf4\u7684\u662f",
        r"\u80fd\u5426\u5177\u4f53",
        r"\u53ef\u4ee5\u5177\u4f53\u8bf4",
        r"\u60f3\u786e\u8ba4",
        r"\u54ea\u4e00\u4e2a",
        r"\u4ec0\u4e48\u610f\u601d",
        r"\u53ef\u4ee5\u9009",
        r"\u6709\u4e24\u4e2a\u65b9\u6848",
        r"\u8981\u4e48",
        r"\u4f60\u53ef\u4ee5\u9009",
        r"\u4f60\u53ef\u4ee5\u8bd5\u8bd5",
        r"\u6211\u4f1a\u8bb0\u4f4f",
        r"\u6211\u4f1a\u6ce8\u610f",
        r"\u4e0b\u6b21\u6211\u4f1a",
        r"\u4ee5\u540e\u6211\u4f1a",
        r"\u6211\u7b54\u5e94",
        r"\u6211\u4f1a\u6539",
        r"\u6211\u4f1a\u8c03\u6574",
        r"\u6211\u4f1a\u966a\u4f60",
        r"\u6211\u610f\u8bc6\u5230",
        r"\u6211\u53cd\u601d",
        r"\u6211\u5e94\u8be5",
        r"\u6211\u505a\u5f97\u4e0d\u597d",
        r"\u6211\u9700\u8981\u6539\u8fdb",
        r"\u6211\u660e\u767d",
        r"\u6211\u7406\u89e3",
    ))
)

_ASSISTANCE = re.compile(
    r"(?:\u5e2e\u6211|\u7ed9\u6211|\u7ffb\u8bd1|\u67e5\u4e00\u4e0b|\u5199\u4e2a|\u4ee3\u7801|\u51fd\u6570|\u62a5\u9519|\u600e\u4e48\u7528|\u600e\u4e48\u914d\u7f6e)"
)
_STRONG_PERSONAL = {
    "explicit_remember",
    "identity_profile",
    "preference_boundary",
    "relationship_family",
    "plan_commitment",
    "privacy_boundary",
    "user_correction",
    "assistant_behavior",
}

def _true_explicit(text: str) -> bool:
    terms = (
        "\u8bb0\u4f4f", "\u8bb0\u4e00\u4e0b", "\u63d0\u9192\u6211",
        "\u63d0\u9192\u4e00\u4e0b\u6211", "\u522b\u5fd8\u4e86", "\u5907\u5fd8",
    )
    return any(term in text for term in terms)


def _true_identity(text: str) -> bool:
    terms = (
        "\u6211\u53eb", "\u6211\u7684\u540d\u5b57", "\u6211\u662f",
        "\u6211\u4f4f\u5728", "\u6211\u7684\u5de5\u4f5c", "\u6211\u5de5\u4f5c",
        "\u6211\u516c\u53f8", "\u6211\u5b66\u6821", "\u6211\u751f\u65e5",
        "\u6211\u7684\u804c\u4e1a", "\u6211\u7684\u8001\u5bb6", "\u6211\u5bb6\u5728",
    )
    if any(q in text for q in (
        "\u6211\u662f\u8c01", "\u6211\u662f\u4ec0\u4e48",
        "\u6211\u662f\u5e72\u4ec0\u4e48", "\u6211\u662f\u505a\u4ec0\u4e48",
        "\u6211\u662f\u54ea",
    )):
        return False
    return any(term in text for term in terms)


def _true_preference(text: str) -> bool:
    terms = (
        "\u6211\u559c\u6b22", "\u6211\u6700\u559c\u6b22", "\u6211\u8ba8\u538c",
        "\u6211\u4e0d\u559c\u6b22", "\u6211\u7231\u5403", "\u6211\u4e0d\u5403",
        "\u6211\u5fcc\u53e3", "\u6211\u8fc7\u654f", "\u6211\u6015",
        "\u6211\u7684\u96f7\u533a", "\u6211\u53d7\u4e0d\u4e86", "\u6211\u5bb3\u6015",
    )
    return any(term in text for term in terms)

def _true_relationship(text: str) -> bool:
    terms = (
        "\u5973\u670b\u53cb", "\u7537\u670b\u53cb", "\u5bf9\u8c61", "\u670b\u53cb",
        "\u5bb6\u4eba", "\u7236\u6bcd", "\u7238\u7238", "\u5988\u5988", "\u7238",
        "\u5988", "\u5b69\u5b50", "\u513f\u5b50", "\u5973\u513f", "\u732b",
        "\u72d7", "\u5ba0\u7269",
    )
    for term in terms:
        if (
            "\u6211\u7684" + term in text
            or "\u6211\u5bb6" + term in text
            or "\u6211\u5bb6\u7684" + term in text
            or "\u6211\u517b" + term in text
            or "\u6211\u517b\u4e86" + term in text
            or "\u6211" + term in text
        ):
            return True
    return False


def _true_plan(text: str) -> bool:
    if any(term in text for term in (
        "\u6211\u6253\u7b97", "\u6211\u8ba1\u5212", "\u6211\u51c6\u5907",
        "\u6211\u7ea6\u4e86", "\u6211\u8981\u53bb", "\u6211\u4eec\u6253\u7b97",
        "\u6211\u4eec\u8ba1\u5212", "\u6211\u4eec\u51c6\u5907", "\u6211\u4eec\u7ea6\u4e86",
        "\u6211\u4eec\u8981\u53bb",
    )):
        return True
    if not ("\u6211" in text or "\u6211\u4eec" in text):
        return False
    dates = (
        "\u4e0b\u5468", "\u4e0b\u4e2a\u6708", "\u660e\u5929", "\u540e\u5929",
        "\u5468\u672b",
    )
    actions = (
        "\u53bb", "\u6765", "\u89c1", "\u51fa\u5dee", "\u9762\u8bd5",
        "\u8003\u8bd5", "\u7ed3\u5a5a", "\u642c\u5bb6", "\u65c5\u884c",
        "\u770b\u75c5", "\u4e0a\u8bfe", "\u4e0a\u73ed", "\u7ea6",
    )
    return any(date in text for date in dates) and any(
        action in text for action in actions
    )


def _refine(text: str, reasons: tuple[str, ...]) -> tuple[float, tuple[str, ...]]:
    """Remove false-positive signal categories before computing the existing weighted score / 在计算既有加权分数前移除误报信号类别。"""
    allowed = set(reasons)
    if "identity_profile" in allowed and not _true_identity(text):
        allowed.discard("identity_profile")
    if "preference_boundary" in allowed and not _true_preference(text):
        allowed.discard("preference_boundary")
    if "relationship_family" in allowed and not _true_relationship(text):
        allowed.discard("relationship_family")
    if "plan_commitment" in allowed and not _true_plan(text):
        allowed.discard("plan_commitment")
    if "explicit_remember" in allowed and not _true_explicit(text):
        allowed.discard("explicit_remember")
    if _ASSISTANCE.search(text) and not (allowed & _STRONG_PERSONAL):
        return 0.0, ()
    ordered = tuple(label for label in reasons if label in allowed)
    return sum(_WEIGHTS.get(label, 0.0) for label in ordered), ordered
