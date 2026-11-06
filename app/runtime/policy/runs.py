"""Pure same-lane admission and supersession policy; no I/O.

纯同 lane 准入与逻辑覆盖策略，不执行读写。
"""

from __future__ import annotations

from ..contracts.runs import ActiveRunView, RunKind, RunTransition, RunTrigger
from ..contracts.sessions import SessionState


class DefaultRunPolicy:
    """Accepted user input supersedes old plans; background work waits for an idle lane.

    已接纳用户输入覆盖旧计划，后台任务等待 lane 空闲。
    """

    def decide(
        self,
        state: SessionState,
        trigger: RunTrigger,
        active: ActiveRunView | None,
    ) -> RunTransition:
        """Return intent without changing state or running work / 只返回意图，不修改状态或执行任务。"""
        if active is None:
            return RunTransition(reason="no_active_run")
        if trigger.kind is RunKind.USER:
            return RunTransition(supersede_active=True, reason="superseded")
        return RunTransition(start_new=False, reason="active_run")
