"""In-memory lane ownership and logical supersession; no host, store or task execution.

进程内 lane 运行归属与逻辑失效，不依赖宿主、存储或执行任务。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import uuid4

from .contracts.runs import ActiveRunView, RunKind, RunTrigger


class RunClosedError(Exception):
    """Finished work reached a checkpoint; not supersession / 已结束运行到达检查点，区别于被覆盖。"""


class RunSupersededError(Exception):
    """An obsolete plan reached a checkpoint; not asyncio cancellation / 旧计划到达检查点，区别于 asyncio 取消。"""


@dataclass(eq=False)
class RunHandle:
    """Run metadata and a validity signal; retain no trigger, message or host task.

    运行元数据及有效性信号，不持有触发对象、消息或宿主任务。
    """

    lane_id: str
    run_id: str
    epoch: int
    kind: RunKind
    started_at: float
    superseded: asyncio.Event = field(default_factory=asyncio.Event, init=False, repr=False)
    supersede_reason: str = field(default="", init=False)
    action_started: bool = field(default=False, init=False)
    closed: bool = field(default=False, init=False)
    _owner: object | None = field(default=None, init=False, repr=False)

    def view(self) -> ActiveRunView:
        """Return a read-only snapshot for policy evaluation / 返回供策略判断的只读快照。"""
        return ActiveRunView(
            self.run_id, self.lane_id, self.epoch, self.kind, self.started_at, self.action_started,
        )

    def supersede(self, reason: str = "superseded") -> bool:
        """Invalidate unstarted actions once; preserve started work and the first reason.

        幂等使未开始动作失效，保留已开始动作及最初原因；不取消宿主任务。
        """
        if not self.is_valid():
            return False
        self.supersede_reason = reason
        self.superseded.set()
        return True

    def is_superseded(self) -> bool:
        """Read logical supersession without changing it / 只读逻辑失效状态。"""
        return self.superseded.is_set()

    def is_valid(self) -> bool:
        """Only unfinished, unsuperseded work may advance / 仅未结束且未被覆盖的运行可继续推进。"""
        return not self.closed and not self.is_superseded()

    def raise_if_invalid(self) -> None:
        """Reject finished or superseded work at a cooperative checkpoint / 在协作检查点拒绝已结束或被覆盖的运行。"""
        if self.closed:
            raise RunClosedError("closed")
        if self.is_superseded():
            raise RunSupersededError(self.supersede_reason)

    def mark_action_started(self) -> None:
        """Check validity and mark the port-call boundary without yielding; not a receipt.

        在端口调用边界检查有效性并记录开始，期间不让出执行权；不代表收到回执。
        """
        self.raise_if_invalid()
        self.action_started = True


class RunControl:
    """Own active handles and an instance epoch on one event-loop thread.

    Callers resolve lanes and admission; finished lane keys are not retained.

    在同一事件循环线程持有活动句柄及实例代次；调用方确认 lane 和准入，不保留已结束 lane 键。
    """

    def __init__(self) -> None:
        self._active: dict[str, RunHandle] = {}
        self._epoch = 0
        self._owner = object()

    def begin(self, lane_id: str, trigger: RunTrigger) -> RunHandle | None:
        """Start admitted work only when this lane has no valid current handle.

        Return None without superseding work; callers must apply supersession explicitly.

        仅在同 lane 没有有效当前句柄时启动；否则返回空，不隐式覆盖，由调用方显式应用覆盖意图。
        """
        previous = self.current(lane_id)
        if previous is not None and previous.is_valid():
            return None
        self._epoch += 1
        handle = RunHandle(lane_id, uuid4().hex, self._epoch, trigger.kind, trigger.now)
        handle._owner = self._owner
        self._active[lane_id] = handle
        return handle

    def finish(self, handle: RunHandle) -> None:
        """Close owned work idempotently; release only the exact current handle.

        幂等关闭本控制器创建的运行；仅移除同一个当前句柄，不影响替代运行或其他控制器。
        """
        if handle._owner is not self._owner:
            return
        handle.closed = True
        if self.current(handle.lane_id) is handle:
            del self._active[handle.lane_id]

    def supersede(self, lane_id: str, run_id: str, reason: str = "superseded") -> bool:
        """Invalidate a matching run once; retain it until finish or replacement.

        按 lane 和运行编号幂等使旧计划失效；句柄保留至结束或替换。
        """
        handle = self.current(lane_id)
        if handle is None or handle.run_id != run_id:
            return False
        return handle.supersede(reason)

    def current(self, lane_id: str) -> RunHandle | None:
        """Read the current handle without creating or advancing a run / 只读当前句柄，不创建运行或推进代次。"""
        return self._active.get(lane_id)
