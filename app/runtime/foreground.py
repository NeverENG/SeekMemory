"""Single-owner, process-local foreground admission / 单所有者的进程内前台准入。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4

from .contracts.scheduling import SchedulingPolicy, TaskPriority, TaskStatus, TaskView
from .policy.scheduling import DefaultSchedulingPolicy


@dataclass
class _Task:
    task_id: str
    agent_id: str
    lane_id: str
    priority: TaskPriority
    status: TaskStatus = TaskStatus.READY

    def view(self) -> TaskView:
        return TaskView(self.task_id, self.agent_id, self.lane_id, self.priority, self.status)


class ForegroundScheduler:
    """Manage cooperative steps on one event-loop thread, without executing or persisting work.

    A caller saves its own progress and checks external actions before acknowledging yield.
    Waiting for external I/O does not imply a safe point or release the slot.
    """

    def __init__(self, policy: SchedulingPolicy | None = None) -> None:
        self._policy = policy or DefaultSchedulingPolicy()
        self._tasks: dict[str, _Task] = {}
        self._ready: list[str] = []
        self._current: str | None = None
        self._consecutive_interactive = 0
        self._changed = asyncio.Event()

    def _notify(self) -> None:
        self._changed.set()
        self._changed = asyncio.Event()

    def submit(self, agent_id: str, lane_id: str, priority: TaskPriority) -> TaskView:
        """Register a pending unit; higher-priority arrivals request, but do not perform, yield."""
        if not agent_id or not lane_id or not isinstance(priority, TaskPriority):
            raise ValueError("agent, lane and priority are required")
        task = _Task(uuid4().hex, agent_id, lane_id, priority)
        self._tasks[task.task_id] = task
        self._ready.append(task.task_id)
        self._request_if_higher(task)
        self._notify()
        return task.view()

    def current(self) -> TaskView | None:
        task = self._tasks.get(self._current) if self._current is not None else None
        return task.view() if task is not None else None

    def view(self, task_id: str) -> TaskView | None:
        task = self._tasks.get(task_id)
        return task.view() if task is not None else None

    async def claim_when_ready(self, task_id: str) -> TaskView | None:
        """Wait without polling for this task to become the next admitted task / 无轮询等待任务准入。"""
        while True:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            if task.status is not TaskStatus.READY:
                return None
            if self._current is None:
                ready = tuple(self._tasks[item].view() for item in self._ready)
                selected = self._pick_ready(ready)
                if selected == task_id:
                    return self._admit(selected)
            changed = self._changed
            await changed.wait()

    def _pick_ready(self, ready: tuple[TaskView, ...]) -> str | None:
        selected = self._policy.pick(ready, self._consecutive_interactive)
        if ready and selected not in {task.task_id for task in ready}:
            raise ValueError("scheduling policy must select a ready task")
        return selected

    def claim_next(self) -> TaskView | None:
        """Grant exactly one foreground slot; a yield request alone never releases it."""
        if self._current is not None:
            return None
        ready = tuple(self._tasks[task_id].view() for task_id in self._ready)
        task_id = self._pick_ready(ready)
        if task_id is None:
            return None
        return self._admit(task_id)

    def _admit(self, task_id: str) -> TaskView:
        self._ready.remove(task_id)
        task = self._tasks[task_id]
        task.status = TaskStatus.RUNNING
        self._current = task_id
        self._consecutive_interactive = (self._consecutive_interactive + 1
                                         if task.priority is TaskPriority.INTERACTIVE else 0)
        return task.view()

    def _request_if_higher(self, incoming: _Task) -> None:
        active = self._tasks.get(self._current) if self._current is not None else None
        if active is not None and active.status is TaskStatus.RUNNING and self._policy.should_yield(
            active.view(), incoming.view()
        ):
            active.status = TaskStatus.YIELD_REQUESTED

    def yield_at_checkpoint(self, task_id: str) -> bool:
        """Acknowledge a safe point only for the current task; the caller retains its progress."""
        if self._current != task_id or self._tasks[task_id].status is not TaskStatus.YIELD_REQUESTED:
            return False
        self._tasks[task_id].status = TaskStatus.SUSPENDED
        self._current = None
        self._notify()
        return True

    def resume(self, task_id: str) -> bool:
        """Requeue only after the workload has verified its own resume cursor and external state."""
        task = self._tasks.get(task_id)
        if task is None or task.status is not TaskStatus.SUSPENDED:
            return False
        task.status = TaskStatus.READY
        self._ready.append(task_id)
        self._request_if_higher(task)
        self._notify()
        return True

    def finish(self, task_id: str) -> bool:
        """Release the exact current task after its external effects have settled."""
        if self._current != task_id:
            return False
        self._current = None
        del self._tasks[task_id]
        self._notify()
        return True

    def abandon(self, task_id: str) -> bool:
        """Remove non-running work; never represent an in-flight action as cancelled."""
        task = self._tasks.get(task_id)
        if task is None or task_id == self._current:
            return False
        if task.status is TaskStatus.READY:
            self._ready.remove(task_id)
        del self._tasks[task_id]
        active = self._tasks.get(self._current) if self._current is not None else None
        if active is not None and active.status is TaskStatus.YIELD_REQUESTED and not any(
            self._policy.should_yield(active.view(), self._tasks[ready].view()) for ready in self._ready
        ):
            active.status = TaskStatus.RUNNING
        self._notify()
        return True
