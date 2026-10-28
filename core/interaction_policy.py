"""Pure relationship-driven interaction policy."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from enum import Enum

from .relationship import HARD_GATE_CONFIDENCE, RelationshipBand, RelationshipSnapshot

# Stable sampling identity and fixed expression limits; not configuration keys.
INTERACTION_POLICY_VERSION = "interaction-v1"
LOW_REPLY_CHARS = 120
DISLIKE_REPLY_CHARS = 60
CLOSE_PROACTIVE_KINDS = ("daily_checkin", "meal_reminder", "goodnight")


class ReplyStyle(str, Enum):
    CUTE = "cute"
    WARM = "warm"
    NEUTRAL = "neutral"
    COOL = "cool"
    MINIMAL = "minimal"


class AffectionScope(str, Enum):
    NONE = "none"
    PRIVATE_ONLY = "private_only"
    PUBLIC_ALLOWED = "public_allowed"


@dataclass(frozen=True)
class InteractionRule:
    style: ReplyStyle
    private_reply_probability: float = 1.0
    group_ambient_probability: float = 1.0
    allow_proactive: bool = False
    allowed_proactive_kinds: tuple[str, ...] = ()
    allow_followup: bool = True
    max_followup_questions: int = 1
    affection_scope: AffectionScope = AffectionScope.NONE
    allow_care_checkin: bool = False
    allow_light_teasing: bool = False
    max_reply_chars: int | None = None


@dataclass(frozen=True)
class InteractionContext:
    source_id: str = ""
    attention: str = "ambient"
    private: bool = False
    must_reply: bool = False


@dataclass(frozen=True)
class InteractionGate:
    enforced: bool = False
    allow_reply: bool = True
    reply_probability: float = 1.0
    allow_proactive: bool = False
    allowed_proactive_kinds: tuple[str, ...] = ()
    allow_followup: bool = True
    max_followup_questions: int = 1
    affection_scope: AffectionScope = AffectionScope.NONE
    allow_care_checkin: bool = False
    allow_light_teasing: bool = False
    max_reply_chars: int | None = None
    style: ReplyStyle = ReplyStyle.NEUTRAL
    reason: str = "relationship_neutral"


@dataclass(frozen=True)
class InteractionPolicySettings:
    """Resolved interaction settings and their canonical core defaults."""

    mode: str = "observe"
    low_private_reply_probability: float = 0.8
    dislike_private_reply_probability: float = 0.5

    def __post_init__(self) -> None:
        if self.mode not in ("off", "observe", "enforce"):
            raise ValueError("relationship mode must be off, observe, or enforce")
        for name in (
            "low_private_reply_probability",
            "dislike_private_reply_probability",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError(f"{name} must be numeric")
            if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
                raise ValueError(f"{name} must be within [0, 1]")


# Reuse the settings defaults instead of repeating configurable probabilities.
_DEFAULT_SETTINGS = InteractionPolicySettings()

_RULES: dict[RelationshipBand, InteractionRule] = {
    RelationshipBand.CLOSE: InteractionRule(
        style=ReplyStyle.CUTE,
        allow_proactive=True,
        allowed_proactive_kinds=CLOSE_PROACTIVE_KINDS,
        affection_scope=AffectionScope.PUBLIC_ALLOWED,
        allow_care_checkin=True,
        allow_light_teasing=True,
    ),
    RelationshipBand.WARM: InteractionRule(
        style=ReplyStyle.WARM,
        allow_proactive=True,
        allow_care_checkin=True,
    ),
    RelationshipBand.NEUTRAL: InteractionRule(style=ReplyStyle.NEUTRAL),
    RelationshipBand.LOW: InteractionRule(
        style=ReplyStyle.COOL,
        private_reply_probability=_DEFAULT_SETTINGS.low_private_reply_probability,
        group_ambient_probability=0.0,
        allow_followup=False,
        max_followup_questions=0,
        max_reply_chars=LOW_REPLY_CHARS,
    ),
    RelationshipBand.DISLIKE: InteractionRule(
        style=ReplyStyle.MINIMAL,
        private_reply_probability=_DEFAULT_SETTINGS.dislike_private_reply_probability,
        group_ambient_probability=0.0,
        allow_followup=False,
        max_followup_questions=0,
        max_reply_chars=DISLIKE_REPLY_CHARS,
    ),
}


def stable_sample(
    source_id: str,
    probability: float,
    policy_version: str = INTERACTION_POLICY_VERSION,
) -> bool:
    """Make a stable Bernoulli decision from one immutable Source id."""
    chance = _probability(probability)
    if chance <= 0.0:
        return False
    if chance >= 1.0:
        return True
    identity = str(source_id or "")
    if not identity:
        return True
    digest = hashlib.sha256(
        f"{policy_version}:{identity}".encode("utf-8")
    ).digest()
    sample = int.from_bytes(digest[:8], "big") / float(1 << 64)
    return sample < chance


def decide_interaction(
    snapshot: RelationshipSnapshot,
    context: InteractionContext,
    settings: InteractionPolicySettings = _DEFAULT_SETTINGS,
) -> InteractionGate:
    """Return a candidate or enforced interaction gate for one WakePolicy result."""
    if settings.mode == "off":
        return InteractionGate(reason="relationship_off")
    band = (
        snapshot.band
        if snapshot.confidence >= HARD_GATE_CONFIDENCE
        else RelationshipBand.NEUTRAL
    )
    rule = _RULES[band]
    probability = 1.0
    allow_reply = True
    reason = f"relationship_{band.value}"
    if context.must_reply:
        reason += "_required"
    elif context.private and band in (RelationshipBand.LOW, RelationshipBand.DISLIKE):
        probability = (
            settings.low_private_reply_probability
            if band is RelationshipBand.LOW
            else settings.dislike_private_reply_probability
        )
        allow_reply = stable_sample(context.source_id, probability)
        reason += "_private_sampled"
    elif not context.private and band in (
        RelationshipBand.LOW,
        RelationshipBand.DISLIKE,
    ):
        probability = rule.group_ambient_probability
        allow_reply = False
        reason += "_group_ambient"

    return InteractionGate(
        enforced=settings.mode == "enforce",
        allow_reply=allow_reply,
        reply_probability=probability,
        allow_proactive=rule.allow_proactive,
        allowed_proactive_kinds=rule.allowed_proactive_kinds,
        allow_followup=rule.allow_followup,
        max_followup_questions=rule.max_followup_questions,
        affection_scope=rule.affection_scope,
        allow_care_checkin=rule.allow_care_checkin,
        allow_light_teasing=rule.allow_light_teasing,
        max_reply_chars=rule.max_reply_chars,
        style=rule.style,
        reason=reason,
    )


def _probability(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("probability must be numeric")
    try:
        chance = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("probability must be numeric") from exc
    if not math.isfinite(chance) or not 0.0 <= chance <= 1.0:
        raise ValueError("probability must be within [0, 1]")
    return chance
