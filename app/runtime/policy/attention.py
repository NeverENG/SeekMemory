"""Pure attention rules for owner, private, direct and follow-up replies; no I/O or scoring.

主人、私聊、直接关注和后续回复的纯注意力规则，不读写或评分。
"""

from __future__ import annotations

from ..contracts import (
    AttentionDecision,
    AttentionLevel,
    RuntimeInput,
    SessionState,
    WakeAction,
)


class DefaultAttentionPolicy:
    """Pure owner/private/direct/follow-up reply rules; no scoring or I/O / 纯主人、私聊、直接关注及后续回复规则，不评分或读写。"""

    def __init__(self, followup_rounds: int = 3, owner_always_reply: bool = True) -> None:
        self.followup_rounds = max(0, int(followup_rounds))
        self.owner_always_reply = bool(owner_always_reply)

    def evaluate(
        self, event: RuntimeInput, state: SessionState, now: float
    ) -> AttentionDecision:
        """Return a decision and follow-up patch without mutating state / 返回决策及后续回复变化，不修改状态。"""
        if not str(event.text or "").strip():
            return AttentionDecision(WakeAction.IGNORE, "empty_text")

        if event.is_owner and self.owner_always_reply:
            return AttentionDecision(
                WakeAction.REPLY,
                "owner",
                attention=AttentionLevel.ADDRESSED,
                must_reply=True,
            )

        if event.private:
            return AttentionDecision(
                WakeAction.REPLY,
                "private_message",
                attention=AttentionLevel.PRIVATE,
                must_reply=True,
            )

        if event.mentioned or event.reply_to_me or event.addressed:
            return AttentionDecision(
                WakeAction.REPLY,
                "direct_attention",
                attention=AttentionLevel.DIRECT,
                must_reply=True,
                followup_speaker_id=str(event.speaker_id or ""),
                followup_remaining=self.followup_rounds,
            )

        remaining = int(state.followup_by_speaker.get(str(event.speaker_id or ""), 0))
        if remaining > 0:
            return AttentionDecision(
                WakeAction.REPLY,
                "followup",
                attention=AttentionLevel.ADDRESSED,
                followup_speaker_id=str(event.speaker_id or ""),
                followup_remaining=remaining - 1,
            )

        return AttentionDecision(
            WakeAction.OBSERVE,
            "ambient_message",
            attention=AttentionLevel.AMBIENT,
        )
