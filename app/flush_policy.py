from __future__ import annotations

from dataclasses import dataclass

from .contracts import DialogueTurn

BACKLOG_QUIET_SECONDS = 30.0


@dataclass(frozen=True)
class FlushDecision:
    should: bool
    reason: str


def select_topic_batches(
    items: list[DialogueTurn], cap: int
) -> list[tuple[str, str, list[DialogueTurn]]]:
    """Pick one topic per session in turn until ``cap`` batches are chosen.

    Round-robin over sessions keeps a single long conversation from occupying
    every slot; sessions with more queued topics contribute again on later passes.

    Args:
        items: queued dialogue turns.
        cap: maximum number of topic batches to return.

    Returns:
        ``(session, topic_id, rows)`` batches in selection order.
    """
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
                 topic_ttl_seconds: float = 86400.0) -> FlushDecision:
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
