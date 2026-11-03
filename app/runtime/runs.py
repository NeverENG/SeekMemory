"""In-memory lane ownership and logical supersession; no host, store or task execution.

进程内 lane 运行归属与逻辑失效，不依赖宿主、存储或执行任务。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from uuid import uuid4

from .contracts.runs import ActiveRunView, RunKind, RunTrigger


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

    def view(self) -> ActiveRunView:
        """Return a read-only snapshot for policy evaluation / 返回供策略判断的只读快照。"""
        return ActiveRunView(
            self.run_id, self.lane_id, self.epoch, self.kind, self.started_at, self.action_started,
        )

    def supersede(self, reason: str = "superseded") -> bool:
        """Invalidate unstarted actions once; preserve started work and the first reason.

        幂等使未开始动作失效，保留已开始动作及最初原因；不取消宿主任务。
        """
        if self.is_superseded():
            return False
        self.supersede_reason = reason
        self.superseded.set()
        return True

    def is_superseded(self) -> bool:
        """Read logical supersession without changing it / 只读逻辑失效状态。"""
        return self.superseded.is_set()

    def raise_if_superseded(self) -> None:
        """Stop an obsolete plan at a cooperative checkpoint / 在协作检查点阻止旧计划继续。"""
        if self.is_superseded():
            raise RunSupersededError(self.supersede_reason)

    def mark_action_started(self) -> None:
        """Check validity and mark the port-call boundary without yielding; not a receipt.

        在端口调用边界检查有效性并记录开始，期间不让出执行权；不代表收到回执。
        """
        self.raise_if_superseded()
        self.action_started = True


class RunControl:
    """Own handles/epochs on one event-loop thread; callers resolve lanes and admission.

    在同一事件循环线程持有句柄/代次；调用方确认 lane 隔离及准入，不推导记忆主体。
    """

    def __init__(self) -> None:
        self._active: dict[str, RunHandle] = {}
        self._epochs: dict[str, int] = {}

    def begin(self, lane_id: str, trigger: RunTrigger) -> RunHandle:
        """Replace admitted work in this lane, leaving other lanes and started actions alone.

        准入后替换同 lane 运行，使旧计划失效；其他 lane 和已开始动作不受干预。
        """
        epoch = self._epochs.get(lane_id, 0) + 1
        handle = RunHandle(lane_id, uuid4().hex, epoch, trigger.kind, trigger.now)
        previous = self.current(lane_id)
        if previous is not None:
            previous.supersede()
        self._epochs[lane_id] = epoch
        self._active[lane_id] = handle
        return handle

    def finish(self, handle: RunHandle) -> None:
        """Release only this exact active handle; retain the lane epoch / 仅释放当前同一句柄，保留 lane 代次。"""
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
