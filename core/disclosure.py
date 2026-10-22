from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .artifact import Artifact, content_of

FULL_MIN = 0.55
PARAPHRASE_MIN = 0.18
HINT_MIN = 0.03


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


def sensitivity_of(art: Artifact) -> float:
    if art.header.family == "secret":
        return 1.0
    scope = str(art.header.scope or "private")
    return {"shared": 0.1, "private": 0.2, "shadow": 0.9}.get(scope, 0.4)


def audience_overlap(art: Artifact, scene: RecallScene,
                    origin_sessions: Iterable[str] = ()) -> float:
    origins = {str(x) for x in origin_sessions if x}
    if scene.session_id and scene.session_id in origins:
        return 1.0
    subject = str(art.header.subject_id or "")
    if subject and subject == scene.speaker_id:
        return 0.50
    if subject and subject in scene.present_ids:
        return 0.25
    return 0.05


def subject_fit(art: Artifact, scene: RecallScene) -> float:
    shareable = str(art.header.shareable or "")
    scope = str(art.header.scope or "")
    if shareable == "public":
        return 1.0
    if scope == "shared" and shareable != "secret":
        return 0.7
    subject = str(art.header.subject_id or "")
    if not subject:
        return 0.5
    if subject == scene.speaker_id:
        return 1.0
    if subject == scene.owner_id and subject in scene.present_ids:
        return 0.7
    return 0.2


def exposure(art: Artifact, scene: RecallScene, relevance: float,
             origin_sessions: Iterable[str] = ()) -> float:
    topic = max(0.0, min(1.0, float(relevance)))
    score = audience_overlap(art, scene, origin_sessions)
    score *= subject_fit(art, scene) * topic * (1.0 - sensitivity_of(art))
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
