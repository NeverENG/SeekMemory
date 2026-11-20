"""Process-local foreground task metadata and policy contracts / 进程内前台任务元数据与策略契约。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Protocol


class TaskPriority(IntEnum):
    BACKGROUND = 1
    INTERACTIVE = 2


class TaskStatus(str, Enum):
    READY = "ready"
    RUNNING = "running"
    YIELD_REQUESTED = "yield_requested"
    SUSPENDED = "suspended"


@dataclass(frozen=True)
class TaskView:
    task_id: str
    agent_id: str
    lane_id: str
    priority: TaskPriority
    status: TaskStatus


class SchedulingPolicy(Protocol):
    """Pure priority decisions; the scheduler alone applies task transitions / 纯策略不修改任务状态。"""

    def pick(self, ready: tuple[TaskView, ...], consecutive_interactive: int) -> str | None:
        ...

    def should_yield(self, active: TaskView, incoming: TaskView) -> bool:
        ...
