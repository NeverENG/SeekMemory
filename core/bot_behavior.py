"""机器人自我描述的有限词表；共享文本只从这里生成。"""
from __future__ import annotations

import math

from .artifact import Artifact
from .persona import (PERSONA_ORIGIN_DREAM, PERSONA_ORIGIN_SEED,
                      PERSONA_SYNTHESIS_VERSION, seed_evolution_matches)

SELF_SUBJECT = "bot:self"
# Internal trust requirements; these do not control user-visible settings.
MIN_EVIDENCE = 3
MIN_CONFIDENCE = 0.9
_MAX_PERSONA_BEHAVIORS = 3
BEHAVIOR_TEXT = {
    "respond_emotion": "她先回应情绪，再讨论问题。",
    "clarify_question": "她在信息不足时先澄清问题。",
    "admit_uncertainty": "她承认不确定，不编造答案。",
    "offer_choices": "她提供选择，尊重对方决定。",
    "protect_privacy": "她保护隐私，不透露私人信息。",
    "correct_mistake": "她发现错误后承认并纠正。",
}
BEHAVIORS = tuple(BEHAVIOR_TEXT)


def confident(value: object) -> bool:
    try:
        number = float(value)
    except (ValueError, TypeError):
        return False
    return math.isfinite(number) and MIN_CONFIDENCE <= number <= 1.0


def compose_behaviors(behaviors: list[str]) -> str:
    """拼装固定的第二人称自述，绝不接受自由文本。"""
    return "".join("你" + BEHAVIOR_TEXT[key][1:] for key in behaviors)


def trusted_self_impression(art: Artifact) -> bool:
    p, h = art.payload, art.header
    kind = p.get("bot_behavior")
    return (
        h.family == "memory" and h.state == "active"
        and h.subject_id == SELF_SUBJECT and h.scope == "shared"
        and h.said_by == "inferred" and confident(h.strength.confidence)
        and p.get("level") == "impression" and p.get("about") == "self"
        and isinstance(kind, str) and kind in BEHAVIOR_TEXT
        and p.get("text") == BEHAVIOR_TEXT[kind]
        and len(set(h.lineage.sources)) >= MIN_EVIDENCE + 1
        and bool(h.lineage.derived_from)
        and h.id not in h.lineage.derived_from
    )


def _trusted_persona_header(art: Artifact) -> bool:
    h = art.header
    return (
        h.family == "persona" and h.state == "active"
        and h.subject_id == SELF_SUBJECT and h.scope == "shared"
        and h.shareable == "public"
    )


def _trusted_behavior_kinds(payload: dict) -> list[str] | None:
    kinds = payload.get("behaviors")
    if not isinstance(kinds, list) or not 1 <= len(kinds) <= _MAX_PERSONA_BEHAVIORS:
        return None
    if any(not isinstance(k, str) or k not in BEHAVIORS for k in kinds):
        return None
    if len(set(kinds)) != len(kinds):
        return None
    return kinds


def trusted_self_persona(art: Artifact) -> bool:
    """Trust the active persona chain, including its one-time seed bootstrap.

    Seed content is explicitly installed configuration, not chat evidence.  It
    therefore has no fabricated lineage.  Dream revisions over a seed must keep
    the deterministic ``base_text + behavior sentence`` shape and the existing
    evidence/confidence requirements.
    """
    if not _trusted_persona_header(art):
        return False
    h, p = art.header, art.payload
    origin = str(p.get("origin") or "")

    if origin == PERSONA_ORIGIN_DREAM and p.get("synthesis") == PERSONA_SYNTHESIS_VERSION:
        return (
            h.said_by == "inferred"
            and confident(h.strength.confidence)
            and isinstance(p.get("text"), str)
            and bool(p["text"].strip())
            and isinstance(p.get("change_reason"), str)
            and bool(p["change_reason"].strip())
            and bool(h.lineage.derived_from)
            and len(set(h.lineage.sources)) >= 1
        )

    if origin == PERSONA_ORIGIN_SEED:
        corpus = p.get("corpus")
        corpus_count = p.get("corpus_count")
        corpus_hash = p.get("corpus_hash")
        if corpus is None:
            corpus_ok = not corpus_count and not corpus_hash
        else:
            corpus_ok = (
                isinstance(corpus, list)
                and bool(corpus)
                and corpus_count == len(corpus)
                and isinstance(corpus_hash, str)
                and bool(corpus_hash)
            )
        return (
            h.said_by == "seed"
            and isinstance(p.get("text"), str)
            and bool(p["text"].strip())
            and isinstance(p.get("seed_id"), str)
            and bool(p["seed_id"].strip())
            and corpus_ok
        )

    kinds = _trusted_behavior_kinds(p)
    if kinds is None:
        return False
    text = p.get("text")

    if origin == PERSONA_ORIGIN_DREAM:
        base_text = p.get("base_text")
        if not seed_evolution_matches(text, base_text, compose_behaviors(kinds)):
            return False
        if p.get("seed_id"):
            corpus_count = p.get("corpus_count")
            corpus_hash = p.get("corpus_hash")
            if corpus_count not in (None, 0):
                if not isinstance(corpus_hash, str) or not corpus_hash:
                    return False
    elif text != compose_behaviors(kinds):
        # Legacy evidence-backed persona without an explicit origin.
        return False

    return (
        h.said_by == "inferred"
        and confident(h.strength.confidence)
        and bool(h.lineage.derived_from)
        and len(set(h.lineage.sources)) >= MIN_EVIDENCE + 1
    )
