"""Group resolved topics and check usage budgets without calls or writes.

为已解析提供方的话题分组并检查用量预算，不调用模型、仓储或调度器。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

try:
    from ..app.contracts import DialogueTurn
    from ..app.flush_policy import ExtractionBatch, chunk_turns, pack_same_session_batches
except ImportError:
    from app.contracts import DialogueTurn
    from app.flush_policy import ExtractionBatch, chunk_turns, pack_same_session_batches


@dataclass(frozen=True)
class ReadyTopic:
    """Selected rows with their resolved provider / 选定的消息及其已解析的提供方。"""

    session_id: str
    topic_id: str
    rows: list[DialogueTurn]
    provider: Any


@dataclass(frozen=True)
class ResolvedBatch:
    """A single-session batch and provider / 单会话批次及提供方。"""

    batch: ExtractionBatch
    provider: Any


@dataclass(frozen=True)
class ExtractionGroup:
    """Batches sharing the existing stop-on-failure rule / 共用现有失败停止规则的批次。"""

    batches: tuple[ResolvedBatch, ...]


def group_batches(ready: list[ReadyTopic], *, triage: bool,
                  token_limit: int, fixed_tokens: int) -> list[ExtractionGroup]:
    """Preserve whole-topic failure groups or pack triaged same-session chunks.

    保留整话题的失败分组，或打包经过重要性筛选的同会话分块；不跨会话混合输入。
    """
    if not triage:
        return [ExtractionGroup(tuple(
            ResolvedBatch(ExtractionBatch(topic.session_id, rows, (topic.topic_id,), 0), topic.provider)
            for rows in chunk_turns(topic.rows)
        )) for topic in ready]
    providers = {topic.session_id: topic.provider for topic in ready}
    units = [(topic.session_id, topic.topic_id, rows)
             for topic in ready for rows in chunk_turns(topic.rows)]
    batches = pack_same_session_batches(units, token_limit=token_limit, fixed_tokens=fixed_tokens)
    return [ExtractionGroup((ResolvedBatch(batch, providers[batch.session_id]),)) for batch in batches]


def budget_reached(*, calls: int, max_calls: int, max_tokens: int,
                    base: dict[str, int], current: dict[str, int]) -> bool:
    """Check completed usage before starting another call / 在开始下一次调用前检查已完成用量。"""
    used = max(0, current["in"] + current["out"] - base["in"] - base["out"])
    return (max_calls > 0 and calls >= max_calls) or (max_tokens > 0 and used >= max_tokens)
