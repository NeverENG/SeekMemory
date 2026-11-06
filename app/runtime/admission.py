"""Source-backed admission and pure-policy application on one event-loop thread.

同一事件循环线程中的 Source 接纳记录与纯策略应用，不执行模型或发送。
"""

from __future__ import annotations

from dataclasses import dataclass
from weakref import ReferenceType, WeakKeyDictionary, ref

from .contracts import (RunKind, RunPolicy, RunTransition, RunTrigger, RuntimeInput,
                        SessionState, TraceSink, UserRunReceipt, WakeAction)
from .recorder import RecordedTurn
from .policy.runs import DefaultRunPolicy
from .runs import RunControl, RunHandle
from .transitions import snapshot


@dataclass(frozen=True)
class _AcceptedInput:
    receipt: ReferenceType[UserRunReceipt]
    event: RuntimeInput


class RunAdmission:
    """Own pending acceptance and caller-held receipts; no historical lane index.

    持有待完成接纳与调用方仍持有的回执，不保留历史 lane 索引。
    """

    def __init__(self, policy: RunPolicy | None = None, trace: TraceSink | None = None) -> None:
        self.policy = policy if policy is not None else DefaultRunPolicy()
        self.trace = trace
        self._control = RunControl()
        self._pending: set[str] = set()
        self._accepted: WeakKeyDictionary[UserRunReceipt, _AcceptedInput] = WeakKeyDictionary()

    def prepare(self, recorded: RecordedTurn) -> bool:
        """Keep failed state acceptance retryable / 保留状态接纳失败后的重试资格。"""
        if recorded.replayed and recorded.source_id not in self._pending:
            return False
        self._pending.add(recorded.source_id)
        return True

    def complete(self, source_id: str) -> None:
        """Release completed or stale acceptance / 释放已完成或过期的接纳记录。"""
        self._pending.discard(source_id)

    def accept(self, state: SessionState, trigger: RunTrigger, receipt: UserRunReceipt) -> None:
        """Bind execution to the caller's receipt; retain it only while the caller does.

        将执行绑定到调用方回执；回执释放后不再保留准入记录。
        """
        if receipt.decision.action is WakeAction.REPLY:
            self._accepted[receipt] = _AcceptedInput(ref(receipt), trigger.event)
        active = self.current(state.session_id)
        if active is not None and active.is_valid():
            self._apply(state, trigger, start=False)

    def begin(self, state: SessionState, trigger: RunTrigger,
              receipt: UserRunReceipt | None = None) -> RunHandle | None:
        """Claim the latest accepted input once; background triggers need no receipt.

        最新已接纳输入仅可领取一次；后台触发无需用户回执。
        """
        if trigger.kind is RunKind.USER:
            accepted = self._accepted.get(receipt) if receipt is not None else None
            if (accepted is None or accepted.receipt() is not receipt
                    or trigger.event != accepted.event
                    or accepted.event.session_id != state.session_id
                    or receipt.read_through_seq != state.last_unread_seq
                    or receipt.read_through_seq <= state.read_through_seq):
                return None
        handle = self._apply(state, trigger, start=True)
        if handle is not None and trigger.kind is RunKind.USER:
            del self._accepted[receipt]
        return handle

    def current(self, lane_id: str) -> RunHandle | None:
        """Read the current handle / 只读当前句柄。"""
        return self._control.current(lane_id)

    def finish(self, handle: RunHandle) -> None:
        """Release only this exact active handle / 仅释放当前同一句柄。"""
        self._control.finish(handle)

    def supersede(self, lane_id: str, run_id: str, reason: str = "superseded") -> bool:
        """Invalidate once and trace only generated run metadata / 幂等使旧计划失效，只诊断生成的运行元数据。"""
        handle = self.current(lane_id)
        if handle is None or not self._control.supersede(lane_id, run_id, reason):
            return False
        self._trace("run_superseded", {
            "run_id": handle.run_id, "epoch": handle.epoch, "kind": handle.kind.value,
        })
        return True

    def _apply(self, state: SessionState, trigger: RunTrigger, *, start: bool) -> RunHandle | None:
        """Apply same-lane intent without consuming Source or scheduling state / 应用同 lane 意图，不消费 Source 或调度状态。"""
        active = self.current(state.session_id)
        view = active.view() if active is not None and active.is_valid() else None
        try:
            transition = self.policy.decide(snapshot(state), trigger, view)
            if not isinstance(transition, RunTransition):
                raise TypeError("run policy must return RunTransition")
        except Exception as exc:
            self._trace("run_policy_failed", {"error": type(exc).__name__})
            transition = DefaultRunPolicy().decide(state, trigger, view)
        if trigger.kind is RunKind.USER and (
                not transition.start_new or (view is not None and not transition.supersede_active)):
            # There is no pending-input reevaluation queue at this boundary.
            # 此边界没有待处理输入重评估队列，不能只保留旧运行而搁置新输入。
            self._trace("run_policy_fallback", {"reason": "no_pending_reevaluation"})
            transition = DefaultRunPolicy().decide(state, trigger, view)
        if active is not None and transition.supersede_active:
            self.supersede(state.session_id, active.run_id)
        if not start or not transition.start_new:
            return None
        if active is not None and active.is_valid():
            return None
        return self._control.begin(state.session_id, trigger)

    def _trace(self, status: str, fields: dict) -> None:
        """Keep diagnostics independent of admission / 诊断失败不影响接纳。"""
        try:
            if self.trace is not None:
                self.trace.record("runtime", status, fields)
        except Exception:
            pass
