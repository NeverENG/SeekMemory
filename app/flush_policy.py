"""Pure extraction gating and same-session batch selection; no writes or scheduling / 纯抽取门控及同会话批次选择，不执行写入或调度。"""

from __future__ import annotations

from dataclasses import dataclass

from .budget import estimate_messages
from .contracts import DialogueTurn

BACKLOG_QUIET_SECONDS = 30.0
MAX_TOPIC_TURNS = 120


@dataclass(frozen=True)
class FlushDecision:
    """Extraction eligibility and its reason; no side effects / 是否允许抽取及原因，没有副作用。"""
    should: bool
    reason: str


@dataclass(frozen=True)
class ExtractionBatch:
    """One session's indivisible input batch and estimated usage / 单会话不可再拆输入批次及估算用量。"""
    session_id: str
    rows: list[DialogueTurn]
    topics: tuple[str, ...]
    estimated_tokens: int


def _is_pair(parent: DialogueTurn, reply: DialogueTurn) -> bool:
    """True when ``reply`` is the assistant answer to ``parent``."""
    if reply.role != "assistant" or parent.role != "user":
        return False
    if reply.session_id != parent.session_id:
        return False
    if reply.reply_to and reply.source_id:
        return str(reply.reply_to) == str(parent.source_id)
    return bool(reply.turn_id) and str(reply.turn_id) == str(parent.turn_id)


def chunk_turns(items: list[DialogueTurn], limit: int = MAX_TOPIC_TURNS) -> list[list[DialogueTurn]]:
    """Split all turns without loss; keep reply pairs together when the limit allows / 完整分块不丢尾部，限额允许时保持问答配对。"""
    size = max(1, int(limit))
    chunks: list[list[DialogueTurn]] = []
    index, total = 0, len(items)
    while index < total:
        end = min(total, index + size)
        if end < total and end - index > 1 and _is_pair(items[end - 1], items[end]):
            end -= 1
        chunks.append(items[index:end])
        index = end
    return chunks


def pack_same_session_batches(
    units: list[tuple[str, str, list[DialogueTurn]]],
    *,
    token_limit: int,
    fixed_tokens: int = 0,
) -> list[ExtractionBatch]:
    """Pack indivisible units in original session order; never mix sessions / 按原会话顺序打包不可拆单元，不混合会话。"""
    limit = max(1, int(token_limit))
    grouped: dict[str, list[tuple[str, list[DialogueTurn]]]] = {}
    session_order: list[str] = []
    for session_id, topic_id, rows in units:
        if session_id not in grouped:
            grouped[session_id] = []
            session_order.append(session_id)
        grouped[session_id].append((topic_id, rows))

    reserved = max(0, int(fixed_tokens))
    batches: list[ExtractionBatch] = []
    for session_id in session_order:
        current_rows: list[DialogueTurn] = []
        current_topics: list[str] = []
        current_text_tokens = 0

        def flush() -> None:
            """Finish this session's batch and reset local accumulation / 完成本会话批次并重置局部累计。"""
            nonlocal current_rows, current_topics, current_text_tokens
            if not current_rows:
                return
            batches.append(
                ExtractionBatch(
                    session_id,
                    current_rows,
                    tuple(current_topics),
                    reserved + current_text_tokens,
                )
            )
            current_rows = []
            current_topics = []
            current_text_tokens = 0

        for topic_id, rows in grouped[session_id]:
            unit_tokens = estimate_messages([turn.text for turn in rows])
            if current_rows and reserved + current_text_tokens + unit_tokens > limit:
                flush()
            current_rows.extend(rows)
            if topic_id not in current_topics:
                current_topics.append(topic_id)
            current_text_tokens += unit_tokens
            if reserved + current_text_tokens > limit:
                flush()
        flush()
    return batches


def select_topic_batches(
    items: list[DialogueTurn], cap: int
) -> list[tuple[str, str, list[DialogueTurn]]]:
    """Select (session, topic, rows) batches round-robin; cap limits the selection / 按会话轮转选择（会话、话题、消息）批次，cap 限制数量。"""
    buckets: dict[str, dict[str, list[DialogueTurn]]] = {}
    order: list[str] = []
    for turn in items:
        session = str(turn.session_id or "")
        if session not in buckets:
            buckets[session] = {}
            order.append(session)
        buckets[session].setdefault(str(turn.topic_id or ""), []).append(turn)
    limit = max(1, int(cap))
    queues = {session: list(buckets[session].items()) for session in order}
    cursors = {session: 0 for session in order}
    selected: list[tuple[str, str, list[DialogueTurn]]] = []
    while len(selected) < limit:
        advanced = False
        for session in order:
            queue = queues[session]
            cursor = cursors[session]
            if cursor >= len(queue):
                continue
            topic_id, rows = queue[cursor]
            cursors[session] = cursor + 1
            selected.append((session, topic_id, rows))
            advanced = True
            if len(selected) >= limit:
                break
        if not advanced:
            break
    return selected


def decide_flush(*, pending: int, idle_seconds: float, worth_now: bool,
                 flushes_today: int, idle_flush_seconds: float,
                 min_pending: int, max_flushes_per_day: int,
                 backlog_flush_at: int,
                 topic_age_seconds: float = 0.0,
                 topic_ttl_seconds: float = 86400.0,
                 dream_only: bool = False) -> FlushDecision:
    # Dream gating precedes even expired topics to prevent daytime extraction.
    # 夜间门控优先于过期话题，避免白天触发抽取。
    """Apply Dream gating before expiry, daily limits, backlog and idle rules / 先检查夜间门控，再判断过期、日限额、积压及空闲条件。"""
    if dream_only:
        return FlushDecision(False, "dream_only")
    if topic_ttl_seconds > 0 and topic_age_seconds >= topic_ttl_seconds:
        return FlushDecision(True, "topic_expired")
    if flushes_today >= max(1, int(max_flushes_per_day)):
        return FlushDecision(False, "daily_cap")
    if backlog_flush_at > 0 and pending >= int(backlog_flush_at):
        quiet_need = BACKLOG_QUIET_SECONDS
        if idle_seconds >= quiet_need:
            return FlushDecision(True, "backlog")
        return FlushDecision(False, "backlog_wait")
    if idle_flush_seconds <= 0:
        return FlushDecision(False, "idle_disabled")
    if pending < max(1, int(min_pending)):
        return FlushDecision(False, "below_min")
    if idle_seconds < idle_flush_seconds:
        return FlushDecision(False, "not_idle")
    if not worth_now:
        return FlushDecision(False, "not_worth")
    return FlushDecision(True, "worth_now")
