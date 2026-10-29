"""Read Source-backed pending topics for proactive candidates without queue consumption.

读取由原始消息支持的待处理话题作为主动候选，不消费队列。
"""

from __future__ import annotations

try:
    from ...app.runtime.topics import TopicCandidate
except ImportError:  # Top-level adapter imports / 顶层适配器导入。
    from app.runtime.topics import TopicCandidate


class AstrBotTopicSource:
    """Read existing pending evidence without consuming queue state / 读取既有待处理证据，不消费队列状态。"""

    def __init__(self, buffer) -> None:
        self.buffer = buffer

    def candidates(
        self, session_id: str, *, now: float, limit: int = 1
    ) -> list[TopicCandidate]:
        """Read bounded candidates for one session using existing validity rules / 按既有有效规则限量读取一个会话的候选。"""
        if limit <= 0 or self.buffer is None:
            return []
        try:
            groups = [
                rows
                for session, _topic_id, rows in self.buffer.topics()
                if str(session) == str(session_id)
            ]
        except Exception:  # noqa: BLE001 - Missing evidence disables proactive topics / 缺少证据时无主动话题。
            return []
        candidates: list[TopicCandidate] = []
        for rows in reversed(groups):
            users = [
                row for row in rows
                if str(getattr(row, "role", "")) == "user"
                and str(getattr(row, "text", "") or "").strip()
            ]
            if not users:
                continue
            last = users[-1]
            memory_ids = tuple(
                str(getattr(row, "source_id", "") or "")
                for row in rows
                if str(getattr(row, "source_id", "") or "")
            )
            candidates.append(TopicCandidate(
                text=str(last.text).strip(),
                kind="unfinished_topic",
                score=0.0,
                memory_ids=memory_ids,
                reason="source_backed_pending_topic",
            ))
            if len(candidates) >= limit:
                break
        return candidates
