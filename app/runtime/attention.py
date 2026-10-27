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


PRESETS: dict[str, AttentionThresholds] = {
    # 话少：只回硬条件，闲聊一律观察；陌生人没有额度
    "quiet": AttentionThresholds(
        owner_cooldown_seconds=60.0, ambient_cooldown_seconds=180.0,
        relevance_reply=0.55, heat_wait=0.9,
        stranger_quota_base=0, stranger_quota_familiar=0, stranger_quota_close=0,
    ),
    # 默认：硬条件 + 相关话题可接，陌生人按印象给额度
    "balanced": AttentionThresholds(
        stranger_quota_base=2, stranger_quota_familiar=3, stranger_quota_close=4,
    ),
    # 话多：更容易接话，群热度也会等
    "chatty": AttentionThresholds(
        owner_cooldown_seconds=10.0, ambient_cooldown_seconds=45.0,
        relevance_reply=0.22, heat_wait=0.35,
        stranger_quota_base=2, stranger_quota_familiar=3, stranger_quota_close=4,
    ),
    # 亲密：主人优先，主动次数更多由 ProactivePolicy 控制，这里只放松接话
    "intimate": AttentionThresholds(
        owner_cooldown_seconds=5.0, ambient_cooldown_seconds=40.0,
        relevance_reply=0.2, heat_wait=0.3,
        stranger_quota_base=1, stranger_quota_familiar=3, stranger_quota_close=4,
    ),
}


def preset(name: str) -> AttentionThresholds:
    """按名字取预设；未知名字退回 balanced。"""
    return PRESETS.get(str(name or "").strip(), PRESETS["balanced"])


def thresholds_from_config(conf) -> AttentionThresholds:
    """从插件配置读取阈值；坏配置退回默认值，不影响聊天。"""
    import json

    try:
        name = conf("attention_preset", "balanced")
    except Exception:  # noqa: BLE001
        name = "balanced"
    base = preset(str(name) if name else "balanced")
    dataclass = type(base)
    try:
        raw = conf("attention_thresholds", "")
    except Exception:  # noqa: BLE001
        raw = ""
    if not raw:
        return base
    try:
        data = json.loads(raw) if isinstance(raw, str) else dict(raw)
    except (TypeError, ValueError):
        return base
    allowed = {field: data[field] for field in dataclass.__dataclass_fields__ if field in data}
    try:
        return dataclass(**{**base.__dict__, **allowed})
    except (TypeError, ValueError):
        return base


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
