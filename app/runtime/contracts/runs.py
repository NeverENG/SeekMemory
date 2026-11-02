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
    """Transient trigger, not audit data; time is explicit and background events are optional.

    使用调用方提供时间的临时触发，后台任务可以没有事件；不作为审计记录。
    """

    kind: RunKind
    event: RuntimeInput | None
    now: float


@dataclass(frozen=True)
class ActiveRunView:
    """Read-only run identity and per-session epoch; no payload or cancellation handle.

    只读运行标识及会话内代次，不携带正文或取消句柄。
    """

    run_id: str
    epoch: int
    kind: RunKind
    started_at: float


@dataclass(frozen=True)
class RunTransition:
    """Pure start/cancel intent; applying it belongs to the runtime.

    仅表达启动及取消意图，由运行时负责执行。
    """

    start_new: bool = True
    cancel_active: bool = False
    reason: str = ""


class RunPolicy(Protocol):
    """Synchronous pure policy; no input mutation, I/O, model calls or action execution.

    同步纯策略，不修改输入、不读写、不调用模型或执行动作。
    """

    def decide(
        self,
        state: SessionState,
        trigger: RunTrigger,
        active: ActiveRunView | None,
    ) -> RunTransition:
        """Describe a run transition without applying it / 描述运行迁移，不执行迁移。"""
        ...
