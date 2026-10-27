"""注意力策略的输入信号：把"她记不记得这个人/这件事"变成可计算值。

信号只读，不写库、不调模型。实现方（服务层）可以复用召回的词面相关度、
印象权重和关系图；策略本身只依赖这个 DTO，方便单测与回放。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import RuntimeInput, SessionState


@dataclass(frozen=True)
class Signals:
    """一次决策所需的只读信号，值域见各字段注释。"""

    relationship: float = 0.0  # 关于该说话人的印象强度 → 0..1
    relevance: float = 0.0     # 当前消息与记忆的相关度 → 0..1
    heat: float = 0.0          # 会话最近活跃度 → 0..1
    recency: float = 0.0       # 距该说话人上次发言的秒数（越大越久）
    window: str = ""           # day / evening / late


class SignalsPort(Protocol):
    """由服务层实现；拿不到信号时返回全默认 Signals，而不是抛错。"""

    def signals(
        self, event: RuntimeInput, state: SessionState, now: float
    ) -> Signals: ...
