"""记忆感知的开口策略：决定"这条消息要不要回"。

纯函数，无 I/O、无宿主依赖；输入是 RuntimeInput + SessionState + Signals。
硬条件（私聊、@、引用、叫名字）不可被阈值否决，策略只能约束闲聊。
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import AttentionLevel, RunDecision, RuntimeInput, SessionState, WakeAction
from .signals import Signals


@dataclass(frozen=True)
class AttentionThresholds:
    """策略阈值；全部可由宿主配置覆盖，默认值是保守起点。"""

    owner_cooldown_seconds: float = 20.0
    ambient_cooldown_seconds: float = 90.0
    relevance_reply: float = 0.35
    relevance_quota: float = 0.15
    heat_wait: float = 0.6
    stranger_quota_base: int = 0
    stranger_quota_familiar: int = 2
    stranger_quota_close: int = 4


class AttentionPolicy:
    """确定性策略：同样的输入永远得到同样的 RunDecision。"""

    def __init__(self, thresholds: AttentionThresholds | None = None) -> None:
        self.t = thresholds or AttentionThresholds()

    def stranger_quota(self, signals: Signals) -> int:
        """陌生人额度：关系越熟允许接的话越多。"""
        if signals.relationship >= 0.6:
            return self.t.stranger_quota_close
        if signals.relationship >= 0.3:
            return self.t.stranger_quota_familiar
        return self.t.stranger_quota_base

    def decide(
        self,
        event: RuntimeInput,
        state: SessionState,
        signals: Signals,
        now: float,
    ) -> RunDecision:
        text = str(event.text or "").strip()
        if not text:
            return RunDecision(WakeAction.IGNORE, "empty_text")

        if event.private:
            return RunDecision(
                WakeAction.REPLY,
                "private_message",
                attention=AttentionLevel.PRIVATE,
                must_reply=True,
            )

        if event.mentioned or event.reply_to_me:
            return RunDecision(
                WakeAction.REPLY,
                "direct_attention",
                attention=AttentionLevel.DIRECT,
                must_reply=True,
            )

        if event.addressed:
            return RunDecision(
                WakeAction.REPLY,
                "addressed",
                attention=AttentionLevel.ADDRESSED,
                must_reply=True,
            )

        if state.quiet_until > now:
            return RunDecision(WakeAction.IGNORE, "quiet_window")

        if event.is_owner:
            # 主人优先，但避免刷屏：冷却期内退化为等待而非静默。
            cooldown = state.last_spoke_at + self.t.owner_cooldown_seconds
            if cooldown > now:
                return RunDecision(WakeAction.WAIT, "owner_cooldown")
            return RunDecision(
                WakeAction.REPLY,
                "owner",
                attention=AttentionLevel.ADDRESSED,
            )

        if event.question and signals.relevance >= self.t.relevance_reply:
            return RunDecision(
                WakeAction.REPLY,
                "relevant_question",
                attention=AttentionLevel.ADDRESSED,
            )

        if signals.relevance >= self.t.relevance_reply or self.stranger_quota(signals) > 0:
            cooldown = state.last_spoke_at + self.t.ambient_cooldown_seconds
            if cooldown > now:
                return RunDecision(WakeAction.WAIT, "ambient_cooldown")
            return RunDecision(
                WakeAction.WAIT,
                "relevant_ambient",
                attention=AttentionLevel.AMBIENT,
            )

        if signals.heat >= self.t.heat_wait:
            return RunDecision(WakeAction.WAIT, "hot_room")

        return RunDecision(
            WakeAction.OBSERVE,
            "ambient_message",
            attention=AttentionLevel.AMBIENT,
        )
