"""Read due session state through a port; policies are pure and no tasks are consumed / 通过端口读取到期会话状态，策略纯计算且不消费任务。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .contracts import ProactivePolicy, SessionState, SessionStateStore
from .proactive import ProactiveDispatchPlan, plan_proactive_dispatch


@dataclass(frozen=True)
class DueRun:
    """One due session, its reason and deadline / 一个到期会话及其原因和期限。"""
    session_id: str
    reason: str
    due_at: float


class TimingPolicy:
    """Pure wait/retry deadline selection / 纯等待及重试期限判断。"""

    def evaluate(self, state: SessionState, now: float) -> DueRun | None:
        """Select a due retry before a due wait; return None when not due / 优先选到期重试，其次到期等待，未到期返回空。"""
        wait_until = float(state.wait_until or 0.0)
        retry_at = float(state.next_retry_at or 0.0)
        if retry_at > 0 and retry_at <= now:
            return DueRun(state.session_id, "retry", retry_at)
        if wait_until > 0 and wait_until <= now:
            return DueRun(state.session_id, "wait", wait_until)
        return None


class Scheduler:
    """Read due sessions through the injected store; never mutate or send / 通过注入存储读取到期会话，不修改或发送。"""

    def __init__(self, store: SessionStateStore, policy: TimingPolicy | None = None) -> None:
        self.store = store
        self.policy = policy or TimingPolicy()

    def due(self, session_ids: Iterable[str], now: float) -> tuple[DueRun, ...]:
        """Read due tasks, isolating broken sessions / 读取到期任务，隔离异常会话。"""
        due: list[DueRun] = []
        for session_id in session_ids:
            try:
                state = self.store.get(str(session_id))
                item = self.policy.evaluate(state, now)
                if item is not None:
                    due.append(item)
            except Exception:  # noqa: BLE001 - isolate broken sessions / 隔离异常会话
                continue
        return tuple(due)

    def proactive_due(
        self,
        session_ids: Iterable[str],
        now: float,
        policy: ProactivePolicy,
        *,
        max_fanout: int = 5,
    ) -> ProactiveDispatchPlan:
        """Read and select proactive candidates without consuming their state / 读取并选择主动候选，不消费状态。"""
        states: list[SessionState] = []
        for session_id in session_ids:
            try:
                states.append(self.store.get(str(session_id)))
            except Exception:  # noqa: BLE001 - isolate broken sessions / 隔离异常会话
                continue
        return plan_proactive_dispatch(
            states, policy, now=now, max_fanout=max_fanout
        )
