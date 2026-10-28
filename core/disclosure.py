from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .artifact import Artifact, content_of

# Internal disclosure policy; only decide() determines the resulting level.
FULL_MIN = 0.55
PARAPHRASE_MIN = 0.18
HINT_MIN = 0.03

# Continuous priors, not visibility gates. Private memory participates in
# retrieval globally; it is simply less likely to be quoted verbatim.
_SCOPE_PRIOR = {
    "shared": 1.0,
    "private": 0.8,
    "shadow": 0.5,
    "secret": 0.1,
}
_DEFAULT_SCOPE_PRIOR = 0.4
_SCOPE_SENSITIVITY = {"shared": 0.1, "private": 0.2, "shadow": 0.9}
_DEFAULT_SENSITIVITY = 0.4
_SPEAKER_CONTEXT_AFFINITY = 0.70
_PRESENT_SUBJECT_CONTEXT_AFFINITY = 0.50
_OTHER_CONTEXT_AFFINITY = 0.22
_SHARED_SUBJECT_FIT = 0.8
_UNKNOWN_SUBJECT_FIT = 0.5
_PRESENT_OWNER_SUBJECT_FIT = 0.8
_OTHER_SUBJECT_FIT = 0.35


class DisclosureLevel(str, Enum):
    FULL = "full"
    PARAPHRASE = "paraphrase"
    HINT = "hint"
    SILENCE = "silence"


@dataclass(frozen=True)
class RecallScene:
    session_id: str
    speaker_id: str
    owner_id: str = ""
    present_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DisclosureDecision:
    level: DisclosureLevel
    score: float
    reason: str


def scope_prior(art: Artifact) -> float:
    """Return the continuous disclosure prior for a memory scope."""
    scope = str(art.header.scope or "private")
    return _SCOPE_PRIOR.get(scope, _DEFAULT_SCOPE_PRIOR)


def sensitivity_of(art: Artifact) -> float:
    """Legacy sensitivity helper retained for secret/shadow compatibility."""
    if art.header.family == "secret":
        return 1.0
    scope = str(art.header.scope or "private")
    return _SCOPE_SENSITIVITY.get(scope, _DEFAULT_SENSITIVITY)


def context_affinity(art: Artifact, scene: RecallScene,
                     origin_sessions: Iterable[str] = ()) -> float:
    """How strongly this memory belongs to the current context.

    Session origin is a bonus, not a gate. A private memory can still reach a
    different conversation when its subject is the current speaker.
    """
    origins = {str(x) for x in origin_sessions if x}
    if scene.session_id and scene.session_id in origins:
        return 1.0
    subject = str(art.header.subject_id or "")
    if subject and subject == scene.speaker_id:
        return _SPEAKER_CONTEXT_AFFINITY
    if subject and subject in scene.present_ids:
        return _PRESENT_SUBJECT_CONTEXT_AFFINITY
    return _OTHER_CONTEXT_AFFINITY


def audience_overlap(art: Artifact, scene: RecallScene,
                     origin_sessions: Iterable[str] = ()) -> float:
    """Backward-compatible alias for the continuous context factor."""
    return context_affinity(art, scene, origin_sessions)


def subject_fit(art: Artifact, scene: RecallScene) -> float:
    shareable = str(art.header.shareable or "")
    scope = str(art.header.scope or "")
    if shareable == "public":
        return 1.0
    if scope == "shared" and shareable != "secret":
        return _SHARED_SUBJECT_FIT
    subject = str(art.header.subject_id or "")
    if not subject:
        return _UNKNOWN_SUBJECT_FIT
    if subject == scene.speaker_id:
        return 1.0
    if subject == scene.owner_id and subject in scene.present_ids:
        return _PRESENT_OWNER_SUBJECT_FIT
    return _OTHER_SUBJECT_FIT


def exposure(art: Artifact, scene: RecallScene, relevance: float,
             origin_sessions: Iterable[str] = ()) -> float:
    topic = max(0.0, min(1.0, float(relevance)))
    score = context_affinity(art, scene, origin_sessions)
    score *= subject_fit(art, scene)
    score *= scope_prior(art)
    score *= max(0.0, 1.0 - sensitivity_of(art))
    score *= topic
    return max(0.0, min(1.0, score))


def decide(art: Artifact, scene: RecallScene, relevance: float,
           origin_sessions: Iterable[str] = ()) -> DisclosureDecision:
    score = exposure(art, scene, relevance, origin_sessions)
    if score >= FULL_MIN:
        return DisclosureDecision(DisclosureLevel.FULL, score, "high exposure")
    if score >= PARAPHRASE_MIN:
        return DisclosureDecision(DisclosureLevel.PARAPHRASE, score, "partial exposure")
    if score >= HINT_MIN:
        return DisclosureDecision(DisclosureLevel.HINT, score, "low exposure")
    return DisclosureDecision(DisclosureLevel.SILENCE, score, "no exposure")


def safe_text(art: Artifact, level: DisclosureLevel) -> str:
    if level == DisclosureLevel.SILENCE:
        return ""
    if level == DisclosureLevel.HINT:
        return "\u4f60\u9690\u7ea6\u8bb0\u5f97\u6709\u4ef6\u76f8\u5173\u7684\u4e8b\u3002"
    if level == DisclosureLevel.FULL:
        try:
            return content_of(art)
        except Exception:
            return ""
    return "\u4f60\u4e4b\u524d\u63d0\u5230\u8fc7\u4e00\u4ef6\u76f8\u5173\u7684\u4e8b\uff0c\u7ec6\u8282\u8fd9\u91cc\u4e0d\u65b9\u4fbf\u5c55\u5f00\u3002"
