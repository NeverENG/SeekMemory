"""Pure session transitions; inputs are copied and no I/O is performed.

纯会话状态变化；复制输入，不执行读写或读取时钟。
"""

from __future__ import annotations

from dataclasses import replace

from .contracts import AttentionDecision, RunDecision, RuntimeInput, SessionState, WakeAction

MAX_FOLLOWUP_SPEAKERS = 64


def snapshot(state: SessionState) -> SessionState:
    """Copy state including the mutable follow-up map / 复制状态及可变的后续回复表。"""
    return replace(state, followup_by_speaker=dict(state.followup_by_speaker))


def observe_event(state: SessionState, event: RuntimeInput, moment: float) -> SessionState:
    """Advance unread counters for a non-stale event / 推进非过期事件的未读计数。"""
    state = snapshot(state)
    event_time = float(event.event_time or 0.0)
    if event_time > 0:
        state.last_event_at = max(state.last_event_at, event_time)
    state.last_seen_at = moment
    observed_seq = max(0, int(event.unread_seq))
    if observed_seq <= int(state.last_unread_seq):
        observed_seq = int(state.last_unread_seq) + 1
    state.last_unread_seq = observed_seq
    state.unread_count = max(
        int(event.unread_count), observed_seq - int(state.read_through_seq), 1
    )
    return state


def apply_attention(state: SessionState, policy_decision: AttentionDecision,
                    moment: float, wait_seconds: float) -> SessionState:
    """Apply a decision without persisting it / 应用决策，不保存状态。"""
    state = snapshot(state)
    speaker_id = str(policy_decision.followup_speaker_id or "")
    if speaker_id and policy_decision.followup_remaining is not None:
        remaining = max(0, int(policy_decision.followup_remaining))
        if remaining:
            state.followup_by_speaker[speaker_id] = remaining
            while len(state.followup_by_speaker) > MAX_FOLLOWUP_SPEAKERS:
                state.followup_by_speaker.pop(next(iter(state.followup_by_speaker)))
        else:
            state.followup_by_speaker.pop(speaker_id, None)
    decision = policy_decision.runtime_decision()
    state.last_action = decision.action.value
    state.last_reason = decision.reason
    if decision.action is WakeAction.REPLY:
        state.ignored_streak = 0
    elif decision.action is WakeAction.IGNORE:
        state.ignored_streak += 1
    if wait_seconds > 0 and decision.action in (
        WakeAction.OBSERVE,
        WakeAction.WAIT,
    ):
        # Debounce new ambient traffic: every ambient event extends the
        # pending wait instead of letting an earlier deadline fire.
        state.wait_until = max(state.wait_until, moment + wait_seconds)
    return state


def schedule_proactive(state: SessionState, delay_seconds: float, moment: float) -> SessionState:
    """Arm a due time after user activity / 用户活动后安排主动时机。"""
    state = snapshot(state)
    delay = max(0.0, float(delay_seconds))
    state.proactive_due_at = moment + delay
    state.proactive_attempts = 0
    state.last_seen_at = moment
    return state


def clear_proactive(state: SessionState) -> SessionState:
    """Clear only the proactive marker / 仅清理主动标记。"""
    state = snapshot(state)
    state.proactive_due_at = 0.0
    return state


def clear_wait(state: SessionState, moment: float) -> SessionState:
    """Clear wait/retry deadlines / 清理等待和重试期限。"""
    state = snapshot(state)
    state.wait_until = 0.0
    state.next_retry_at = 0.0
    state.last_seen_at = moment
    return state


def claim_dispatch(state: SessionState, source_id: str, moment: float) -> SessionState:
    """Count an attempt while retaining durable deadlines / 累计尝试并保留持久期限。"""
    state = snapshot(state)
    sid = str(source_id or "")
    if state.last_dispatched_source_id != sid:
        state.dispatch_attempts = 0
    state.last_dispatched_source_id = sid
    state.dispatch_attempts += 1
    state.last_seen_at = moment
    return state


def schedule_retry(state: SessionState, now: float, attempts: int,
                   max_attempts: int = 3, base_seconds: float = 2.0,
                   cap_seconds: float = 60.0, claimed: SessionState | None = None) -> SessionState:
    """Retry old work without overwriting new messages / 重试旧任务，不覆盖新消息。"""
    if claimed is not None:
        # Do not resurrect input already acknowledged by another delivery,
        # or overwrite work/deadlines installed after this claim. Unchanged
        # retained markers still belong to this failed attempt.
        if (pending_changed(state, claimed)
                or (state.read_through_seq > claimed.read_through_seq
                    and state.read_through_seq >= claimed.last_unread_seq)):
            return state
    tries = max(1, int(attempts))
    if (claimed is not None and state.last_unread_seq > claimed.last_unread_seq
            and tries >= max(1, int(max_attempts))):
        # Exhaustion belongs to the old Source. The retained marker lets
        # the worker pick up the newer Source with its own attempt budget.
        return state
    state = snapshot(state)
    if tries >= max(1, int(max_attempts)):
        state.wait_until = 0.0
        state.next_retry_at = 0.0
        state.last_reason = "dispatch_dead"
    else:
        delay = min(max(0.0, float(cap_seconds)),
                    max(0.1, float(base_seconds)) * (2 ** (tries - 1)))
        state.wait_until = float(now) + delay
        state.next_retry_at = state.wait_until
        state.last_reason = "dispatch_retry"
    state.last_action = "wait"
    return state


def mark_delivered(state: SessionState, moment: float, *,
                   claimed: SessionState | None = None,
                   read_through_seq: int | None = None) -> SessionState:
    """Acknowledge a bounded read cursor without time regression / 有界确认已读位置，时间不倒退。"""
    state = snapshot(state)
    state.last_spoke_at = max(state.last_spoke_at, moment)
    if read_through_seq is not None:
        cursor = min(state.last_unread_seq, max(0, int(read_through_seq)))
        advanced = cursor > state.read_through_seq
        state.read_through_seq = max(state.read_through_seq, cursor)
        state.unread_count = max(0, state.last_unread_seq - state.read_through_seq)
        current_claim = claimed is not None and not pending_changed(state, claimed)
        if cursor >= state.last_unread_seq and (
            current_claim or (claimed is None and advanced)
        ):
            state.wait_until = 0.0
            state.next_retry_at = 0.0
            state.dispatch_attempts = 0
    return state


def pending_changed(state: SessionState, claimed: SessionState) -> bool:
    """Detect work installed after the claim / 检测领取任务后安排的新任务。"""
    return (
        state.last_dispatched_source_id != claimed.last_dispatched_source_id
        or state.wait_until != claimed.wait_until
        or state.next_retry_at != claimed.next_retry_at
    )


def finish_proactive(state: SessionState, moment: float, reason: str,
                     claimed: SessionState | None) -> SessionState:
    """Finish only the claimed proactive marker, retaining new user work.

    仅完成已领取的主动任务，保留后来用户消息安排的新任务。
    """
    state = snapshot(state)
    state.last_proactive_at = max(state.last_proactive_at, moment)
    if claimed is None or (
        state.proactive_due_at == claimed.proactive_due_at
        and state.proactive_attempts == claimed.proactive_attempts
        and state.last_seen_at == claimed.last_seen_at
    ):
        state.proactive_attempts = int(state.proactive_attempts or 0) + 1
        state.proactive_due_at = 0.0
        state.last_action = "reply"
        state.last_reason = reason
    return state
