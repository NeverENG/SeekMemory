"""Pure foreground priority selection / 纯前台优先级策略。"""

from __future__ import annotations

from ..contracts.scheduling import TaskPriority, TaskView


class DefaultSchedulingPolicy:
    """Interactive first, FIFO within a class; admit one waiting background after three interactive claims."""

    def pick(self, ready: tuple[TaskView, ...], consecutive_interactive: int) -> str | None:
        interactive = next((task for task in ready if task.priority is TaskPriority.INTERACTIVE), None)
        background = next((task for task in ready if task.priority is TaskPriority.BACKGROUND), None)
        if background is not None and (interactive is None or consecutive_interactive >= 3):
            return background.task_id
        return interactive.task_id if interactive is not None else None

    def should_yield(self, active: TaskView, incoming: TaskView) -> bool:
        return incoming.priority > active.priority
