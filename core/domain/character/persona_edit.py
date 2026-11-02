"""Reauthor explicitly edited trusted persona text using existing seed semantics.

将明确编辑的可信人格正文保存为既有人工设定语义，不放宽披露检查。
"""
from __future__ import annotations

from dataclasses import replace

from ..memory.artifact import Artifact
from .bot_behavior import trusted_self_persona
from .persona import PERSONA_ORIGIN_SEED

# Includes duplicated deterministic base text and retained authored metadata.
MAX_PERSONA_PAYLOAD_BYTES = 192 * 1024


def authored_persona_edit(current: Artifact, replacement: Artifact) -> Artifact:
    """Keep evidence/history while making manually changed grown text authored.

    保留证据及历史，将手工修改的成长正文作为人工设定。
    """
    if (not trusted_self_persona(current)
            or current.payload.get("origin") == PERSONA_ORIGIN_SEED
            or replacement.header.scope != "shared"
            or replacement.header.state != "active"
            or replacement.payload.get("text") == current.payload.get("text")):
        return replacement
    payload = dict(replacement.payload)
    payload["origin"] = PERSONA_ORIGIN_SEED
    # Legacy evidence-only personas have no pack identity; use their own ID for
    # the authored configuration, never infer a matching pack or create Sources.
    payload["seed_id"] = str(current.payload.get("seed_id") or current.header.id)
    for key in ("base_text", "behaviors", "synthesis", "change_reason"):
        payload.pop(key, None)
    # Dream stores corpus provenance without its content. That provenance stays
    # in the historical revision; the new authored baseline has no such corpus.
    if payload.get("corpus") is None:
        payload["corpus_count"] = 0
        payload["corpus_hash"] = ""
    return replace(replacement, payload=payload,
                   header=replace(replacement.header, said_by=PERSONA_ORIGIN_SEED))
