"""Pure wake policy: decide whether the bot should act on one inbound event."""

from __future__ import annotations

from .contracts import (
    AttentionLevel,
    RunDecision,
    RuntimeInput,
    SessionState,
    WakeAction,
)


class WakePolicy:
    """Deterministic policy with no I/O and no AstrBot imports.

    ``wait`` is a defer for ambient group traffic, never a mute for private
    messages or direct attention. Private messages and @/reply-to-bot are hard
    attention and must keep a reply path.
    """

    def evaluate(
        self, event: RuntimeInput, state: SessionState, now: float
    ) -> RunDecision:
        moment = float(now)
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

        direct = event.mentioned
        if direct:
            return RunDecision(
                WakeAction.REPLY,
                "direct_attention",
                attention=AttentionLevel.DIRECT,
                must_reply=True,
            )

        if state.quiet_until > moment:
            return RunDecision(
                WakeAction.IGNORE,
                "quiet_window",
                attention=AttentionLevel.AMBIENT,
            )

        if event.question:
            return RunDecision(
                WakeAction.REPLY,
                "question",
                attention=AttentionLevel.ADDRESSED,
            )
        if state.wait_until > moment:
            return RunDecision(
                WakeAction.WAIT,
                "waiting",
                attention=AttentionLevel.AMBIENT,
            )

        cooldown_until = state.cooldown_until
        if not cooldown_until and state.last_spoke_at:
            cooldown_until = state.last_spoke_at + state.reply_cooldown_seconds
        if cooldown_until > moment:
            return RunDecision(
                WakeAction.IGNORE,
                "reply_cooldown",
                attention=AttentionLevel.AMBIENT,
            )

        return RunDecision(
            WakeAction.OBSERVE,
            "ambient_message",
            attention=AttentionLevel.AMBIENT,
        )
