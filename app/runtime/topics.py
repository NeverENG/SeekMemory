"""Read-only proactive topic data and ranking; never decide or execute sending / 只读主动话题数据及排序，不决定或执行发送。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TopicCandidate:
    """Read-only proactive topic supplied from memory / 从记忆提供的只读主动话题。"""

    text: str
    kind: str = ""
    score: float = 0.0
    memory_ids: tuple[str, ...] = ()
    reason: str = ""


class TopicSource(Protocol):
    """Injected read-only topic source for one session / 按会话注入的只读话题来源。"""

    def candidates(
        self, session_id: str, *, now: float, limit: int = 1
    ) -> list[TopicCandidate]:
        """Read bounded candidates at the explicit time / 按显式时间限量读取候选。"""
        ...


def rank(candidates: list[TopicCandidate], limit: int = 1) -> list[TopicCandidate]:
    """Order by descending score then text and return a bounded list / 按分数降序及文本排序，返回有界列表。"""
    if limit <= 0:
        return []
    return sorted(candidates, key=lambda item: (-float(item.score), item.text))[:limit]
