"""Pure proactive decision data and required policy declaration / 纯主动发言决策数据及所需策略声明。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .sessions import SessionState
@dataclass(frozen=True)
class ProactiveDecision:
    """Pure eligibility result and next due time / 纯主动发言资格结果及下次到期时间。"""

    should_speak: bool
    reason: str
    due_at: float = 0.0


class ProactivePolicy(Protocol):
    """Injected pure proactive eligibility rules / 注入的纯主动发言资格规则。"""
    def evaluate(self, state: SessionState, *, now: float) -> ProactiveDecision:
        """Evaluate explicit time without state mutation / 根据显式时间判断，不修改状态。"""
        ...
