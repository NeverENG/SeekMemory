"""Prepare sentence-level persona proposals without changing persona artifacts."""
from __future__ import annotations

import difflib
import re

from core.domain.character.bot_behavior import SELF_SUBJECT, compose_behaviors
from maintain.persona_policy import prepare_persona
from maintain.self_impression import promote_self_candidates


def sentence_diff(old_text: str, new_text: str) -> list[dict[str, str]]:
    """Keep punctuation, align sentences, and show only changed sentence groups."""
    if len(old_text) > 2000 or len(new_text) > 2000:
        raise ValueError("persona_text_too_long")
    split = lambda value: [part for part in
                           re.split(r"(?<=[。！？.!?；;])|(?<=\n)", value) if part.strip()]
    before, after = split(old_text), split(new_text)
    if len(before) > 80 or len(after) > 80:
        raise ValueError("persona_too_many_sentences")
    result = [
        {"old": "".join(before[i:j]), "new": "".join(after[k:l])}
        for tag, i, j, k, l in difflib.SequenceMatcher(
            a=before, b=after, autojunk=False
        ).get_opcodes() if tag != "equal"
    ]
    return result


def propose_candidate(proposals, subject_key: str, current, candidate,
                      reason: str) -> dict | None:
    """Persist only a draft; never call ArtifactStore.commit here."""
    if proposals is None or not subject_key:
        raise RuntimeError("persona_proposal_store_unavailable")
    old_text = str(current.payload.get("text") or "") if current else ""
    new_text = str(candidate.payload.get("text") or "").strip()
    if not new_text.strip() or old_text == new_text:
        return None
    return proposals.create(
        subject_key=subject_key,
        persona_id=str(current.header.id) if current else "",
        base_revision=int(current.header.revision) if current else 0,
        old_text=old_text, new_text=new_text,
        diff=sentence_diff(old_text, new_text), reason=reason,
    )


def propose_self_persona(proposals, subject_key: str, sources, cache,
                         today: str | None = None) -> dict | None:
    """Use the existing deterministic candidate algorithm, replacing only its write."""
    if proposals is None or not subject_key:
        raise RuntimeError("persona_proposal_store_unavailable")
    candidates = promote_self_candidates(cache, sources, today)
    old = sorted(cache.active("persona"), key=lambda art: (
        art.header.subject_id != SELF_SUBJECT, art.header.time.created, art.header.id
    ))
    prepared = prepare_persona(candidates, old)
    if prepared.persona is None:
        return None
    # An approved draft goes through the unchanged authored-write path.  If
    # its exact inferred behavior paragraph is already in her own text, do
    # not propose appending that same paragraph again on the next tick.
    if old:
        trait = compose_behaviors(prepared.persona.payload.get("behaviors") or [])
        current_text = str(old[0].payload.get("text") or "")
        if trait and (current_text == trait or "\n" + trait in current_text):
            return None
    return propose_candidate(
        proposals, subject_key, old[0] if old else None,
        prepared.persona, "self-only stable persona and consolidation",
    )
