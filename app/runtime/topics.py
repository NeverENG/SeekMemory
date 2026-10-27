"""主动说话的话题候选：只负责"有什么由头可说"，不决定"什么时候说"。

排程、冷却、重试归 ProactivePolicy（#117）；这里提供确定性候选与排序，
方便单测和替换数据源（记忆、日程、外部事件）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TopicCandidate:
    """一个可主动发起的话题；memory_ids 用于回指与冷却去重。"""

    text: str
    kind: str = ""  # unfinished_scene / impression_change / relation_gap / topic
    score: float = 0.0
    memory_ids: tuple[str, ...] = ()
    reason: str = ""


class TopicSource(Protocol):
    """候选来源；拿不到时返回空列表，不抛错。"""

    def candidates(self, now: float, limit: int = 3) -> list[TopicCandidate]: ...


def rank(candidates: list[TopicCandidate], limit: int = 3) -> list[TopicCandidate]:
    """按分数排序取前 N 条，同分时保持输入顺序（稳定排序）。"""
    if limit <= 0:
        return []
    ordered = sorted(candidates, key=lambda item: (-float(item.score), item.text))
    return ordered[:limit]


def usable(candidate: TopicCandidate, recent_ids: set[str]) -> bool:
    """过滤掉还在冷却期内的话题（按 memory_ids 去重）。"""
    ids = set(str(mid) for mid in candidate.memory_ids if mid)
    return not (ids & set(recent_ids))
