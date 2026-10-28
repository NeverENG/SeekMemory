"""Default host-neutral attention policy.

The policy is intentionally small: direct attention gets a reply, owner gets a
reply, and a non-owner direct interaction opens a short per-speaker follow-up
window. It contains no platform, group, relationship, quota or scoring logic.
"""

from __future__ import annotations

from .contracts import (
    AttentionDecision,
    AttentionLevel,
    RuntimeInput,
    SessionState,
    WakeAction,
)


class DefaultAttentionPolicy:
    """Minimal deterministic reply policy used by AgentRuntime."""

    def __init__(self, followup_rounds: int = 3, owner_always_reply: bool = True) -> None:
        self.followup_rounds = max(0, int(followup_rounds))
        self.owner_always_reply = bool(owner_always_reply)

    def evaluate(
        self, event: RuntimeInput, state: SessionState, now: float
    ) -> AttentionDecision:
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
