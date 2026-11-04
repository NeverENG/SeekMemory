"""Host-neutral run data and policy contract; no execution or I/O.

与宿主无关的运行数据及策略契约，不执行任务或读写。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .events import RuntimeInput
from .sessions import SessionState


class RunKind(str, Enum):
    """Origin of a run, independent of its host / 与宿主无关的运行来源。"""

    USER = "user"
    DEFERRED = "deferred"
    PROACTIVE = "proactive"


@dataclass(frozen=True)
class RunTrigger:
    """Transient admitted trigger with explicit time; background events are optional.

    Callers accept user input and reject stale/replayed events before policy evaluation.
    This value does not perform admission or become audit data.

    携带显式时间的临时触发，后台事件可为空；调用方先接纳用户输入并排除过期/重放。
    本对象不执行接纳判断，也不作为审计记录。
    """

    kind: RunKind
    event: RuntimeInput | None
    now: float


@dataclass(frozen=True)
class ActiveRunView:
    """Read-only lane-local metadata; action_started records a boundary, not its outcome.

    lane_id is scoped to one Runtime instance, not a memory subject or persisted key.
    epoch increases across the instance; values within a lane need not be consecutive.

    只读 lane 内运行元数据；action_started 仅表示已跨过动作开始边界，不表示结果。
    lane_id 仅在当前 Runtime 实例内有效，不是记忆主体或持久化键。
    epoch 在实例内递增，同 lane 的代次不要求连续。
    """

    run_id: str
    lane_id: str
    epoch: int
    kind: RunKind
    started_at: float
    action_started: bool = False


@dataclass(frozen=True)
class RunTransition:
    """Same-lane admission and logical supersession intent, applied by the runtime.

    Supersession blocks unstarted actions; it does not abort calls, undo effects or yield.
    start_new alone never authorizes replacement: a valid active run must first be
    explicitly superseded, otherwise begin() refuses the new run.

    表达同 lane 准入及逻辑覆盖意图，由运行时应用；覆盖阻止未开始动作，
    不表示调用已终止、副作用已撤销或任务已让位。
    start_new 本身不授权替换；须先显式覆盖有效旧运行，否则 begin() 拒绝新运行。
    """

    start_new: bool = True
    supersede_active: bool = False
    reason: str = ""


class RunPolicy(Protocol):
    """Pure same-lane policy; no mutation, I/O, global priority or YIELD decisions.

    Runtime supplies admitted input and a same-lane active view. Keeping active work
    requires reliable pending input and later reevaluation; otherwise use the default.

    同步纯策略，不修改输入、不读写，也不决定全局优先级或 YIELD。
    Runtime 提供已接纳输入及同 lane 视图；保留旧运行须有可靠待处理入口和后续重评估，
    否则回退默认策略。
    """

    def decide(
        self,
        state: SessionState,
        trigger: RunTrigger,
        active: ActiveRunView | None,
    ) -> RunTransition:
        """Describe a run transition without applying it / 描述运行迁移，不执行迁移。"""
        ...
