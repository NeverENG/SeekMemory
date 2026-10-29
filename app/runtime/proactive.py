"""Pure proactive selection and timing rules; no clock reads or persistence / 纯主动选择及时间规则，不读取时钟或持久化。"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from .contracts import ProactiveDecision, ProactivePolicy, SessionState


@dataclass(frozen=True)
class ProactiveCandidate:
    """One eligible session and its pure policy decision / 一个合格会话及其纯策略决策。"""

    session_id: str
    decision: ProactiveDecision


@dataclass(frozen=True)
class ProactiveDispatchPlan:
    """Selected bounded work and still-due deferred sessions / 选中的有界任务及仍到期的延后会话。"""

    selected: tuple[ProactiveCandidate, ...] = ()
    deferred: tuple[ProactiveCandidate, ...] = ()

    @property
    def eligible_count(self) -> int:
        """Count selected and deferred eligible sessions / 统计已选及延后合格会话。"""
        return len(self.selected) + len(self.deferred)


def plan_proactive_dispatch(
    states: Iterable[SessionState],
    policy: ProactivePolicy,
    *,
    now: float,
    max_fanout: int,
) -> ProactiveDispatchPlan:
    """Sort eligible sessions deterministically, without consuming deferred work / 确定性排序合格会话，不消费延后任务。"""
    limit = int(max_fanout)
    if limit < 0:
        raise ValueError("max_fanout must be non-negative")

    candidates: list[ProactiveCandidate] = []
    seen: set[str] = set()
    for state in states:
        session_id = str(state.session_id or "")
        if not session_id or session_id in seen:
            continue
        seen.add(session_id)
        decision = policy.evaluate(state, now=now)
        if decision.should_speak:
            candidates.append(ProactiveCandidate(session_id, decision))

    candidates.sort(key=lambda item: (
        item.decision.due_at,
        item.session_id,
    ))
    return ProactiveDispatchPlan(
        selected=tuple(candidates[:limit]),
        deferred=tuple(candidates[limit:]),
    )


def _timestamp(value: object) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return result if math.isfinite(result) and result > 0.0 else 0.0


def _count(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError, OverflowError):
        return 0


class DefaultProactivePolicy:
    """Pure cooldown/retry/quiet rules; disabled by default and never reads a clock / 纯冷却、重试、安静期规则，默认关闭且不读取时钟。"""

    _MAX_BACKOFF_EXPONENT = 20

    def __init__(
        self,
        *,
        enabled: bool = False,
        cooldown_seconds: float = 3600.0,
        retry_seconds: float = 300.0,
        max_attempts: int = 3,
        ignored_streak_limit: int = 3,
        ignored_backoff_seconds: float = 600.0,
    ) -> None:
        self.enabled = bool(enabled)
        self.cooldown_seconds = self._duration(cooldown_seconds)
        self.retry_seconds = self._duration(retry_seconds)
        self.ignored_backoff_seconds = self._duration(ignored_backoff_seconds)
        self.max_attempts = max(1, int(max_attempts))
        self.ignored_streak_limit = max(1, int(ignored_streak_limit))

    @staticmethod
    def _duration(value: float) -> float:
        duration = float(value)
        if not math.isfinite(duration) or duration < 0.0:
            raise ValueError("policy durations must be finite and non-negative")
        return duration

    def evaluate(self, state: SessionState, *, now: float) -> ProactiveDecision:
        """Return eligibility and next due time without mutating state / 返回资格及下次到期时间，不修改状态。"""
        try:
            moment = float(now)
        except (TypeError, ValueError, OverflowError):
            moment = math.nan
        scheduled_at = _timestamp(state.proactive_due_at)
        if not math.isfinite(moment):
            return ProactiveDecision(False, "invalid_time", scheduled_at)
        if not self.enabled:
            return ProactiveDecision(False, "disabled", scheduled_at)
        if scheduled_at <= 0.0:
            return ProactiveDecision(False, "not_scheduled", 0.0)

        attempts = _count(state.proactive_attempts)
        if attempts >= self.max_attempts:
            return ProactiveDecision(False, "max_attempts", 0.0)

        gates: list[tuple[float, str]] = [(scheduled_at, "not_due")]
        quiet_until = _timestamp(state.quiet_until)
        if quiet_until > 0.0:
            gates.append((quiet_until, "quiet_window"))

        last_proactive_at = _timestamp(state.last_proactive_at)
        if last_proactive_at > 0.0:
            cooldown_until = last_proactive_at + self.cooldown_seconds
            if cooldown_until > 0.0:
                gates.append((cooldown_until, "cooldown"))
            if attempts > 0 and self.retry_seconds > 0.0:
                gates.append((last_proactive_at + self.retry_seconds, "retry_wait"))

        ignored_streak = _count(state.ignored_streak)
        if ignored_streak >= self.ignored_streak_limit and self.ignored_backoff_seconds:
            exponent = min(
                ignored_streak - self.ignored_streak_limit,
                self._MAX_BACKOFF_EXPONENT,
            )
            backoff_base = max(
                _timestamp(state.last_seen_at), last_proactive_at
            )
            gates.append((
                backoff_base + self.ignored_backoff_seconds * (2 ** exponent),
                "ignored_backoff",
            ))

        eligible_at, blocking_reason = max(gates, key=lambda gate: gate[0])
        if moment < eligible_at:
            return ProactiveDecision(False, blocking_reason, eligible_at)
        reason = "retry_due" if attempts > 0 else "due"
        return ProactiveDecision(True, reason, eligible_at)
