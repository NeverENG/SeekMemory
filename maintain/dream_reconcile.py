"""Prepare a narrow, offline-only Dream correction plan without writing data.

仅为显式同会话更正准备最小离线计划；未接入自动 Dream 调度。
"""
from __future__ import annotations

import re
from datetime import datetime

from .plans import RevisionPlan, RevisionWrite
from .ports import ArtifactStore, SourceStore

try:
    from ..core.domain.memory.artifact import Lineage, revise, validate
    from ..core.port.tree import TreeEdgeReader
except ImportError:
    from core.domain.memory.artifact import Lineage, revise, validate
    from core.port.tree import TreeEdgeReader

_CORRECTION = re.compile(r"^\s*(?:更正[：:]|correction:)", re.IGNORECASE)


def _instant(value: str) -> datetime | None:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError):
        return None
    return stamp if stamp.tzinfo is not None and stamp.utcoffset() is not None else None


def prepare_source_correction(
    artifacts: ArtifactStore,
    sources: SourceStore,
    edges: TreeEdgeReader,
    child_id: str,
    correction_source_id: str,
) -> RevisionPlan | None:
    """Prepare an atomic fact correction and retire its sole unsupported parent.

    Accept only an explicit reply to the child's sole original Source and an
    identical, single-child parent. Ambiguous or unsupported cases stay untouched.
    The caller owns any later persistence; this function is not scheduled by Dream.

    仅处理有明确回复证据、一个子事实及一个完全同文父结论的离线样例；其他情况不写入。
    """
    child = artifacts.get(child_id) if child_id else None
    if (
        child is None or child.header.family != "memory" or child.header.state != "active"
        or child.header.scope != "private" or child.header.shareable != "private_only"
        or child.payload.get("level") != "fact"
        or set(child.payload) != {"level", "text"}
        or len(child.header.lineage.sources) != 1 or child.header.lineage.derived_from
        or not child.header.subject_id
    ):
        return None
    old_id = child.header.lineage.sources[0]
    evidence = sources.sources_by_ids([old_id, correction_source_id])
    original, correction = evidence.get(old_id), evidence.get(correction_source_id)
    if original is None or correction is None or original.id == correction.id:
        return None
    old_at, corrected_at = _instant(original.at), _instant(correction.at)
    if (
        original.role != "user" or correction.role != "user"
        or original.speaker_id != child.header.subject_id
        or correction.speaker_id != original.speaker_id
        or not original.session_id or correction.session_id != original.session_id
        or correction.reply_to != original.id or not _CORRECTION.match(correction.text)
        or old_at is None or corrected_at is None or corrected_at <= old_at
    ):
        return None
    # A wider graph needs dependency enumeration and edge recovery first. Do not
    # modify only one side of an ambiguous hierarchy.
    parent_ids = tuple(edges.tree_parents(child_id, 2))
    if len(parent_ids) != 1:
        return None
    # Legacy/partially written hierarchy may express a dependency in lineage
    # without an edge. Never retire only the visible parent in that case.
    dependents = {
        item.header.id for item in artifacts.list("memory", "active")
        if child_id in item.header.lineage.derived_from
    }
    if dependents != {parent_ids[0]}:
        return None
    parent = artifacts.get(parent_ids[0])
    if (
        parent is None or parent.header.family != "memory" or parent.header.state != "active"
        or parent.header.scope != child.header.scope
        or parent.header.shareable != child.header.shareable
        or parent.header.subject_id != child.header.subject_id
        or parent.payload.get("level") != "impression"
        or set(parent.payload) != {"level", "text"}
        or parent.payload["text"] != child.payload["text"]
        or parent.header.lineage.sources != (original.id,)
        or parent.header.lineage.derived_from != (child_id,)
    ):
        return None
    evidence_ids = (original.id, correction.id)
    revised_child = revise(
        child, payload={**child.payload, "text": correction.text},
        lineage=Lineage(sources=evidence_ids),
    )
    retired_parent = revise(
        parent, state="forgotten",
        lineage=Lineage(sources=evidence_ids, derived_from=(child_id,)),
    )
    validate(revised_child)
    validate(retired_parent)
    return RevisionPlan((
        RevisionWrite(revised_child, child.header.revision, evidence_ids),
        RevisionWrite(retired_parent, parent.header.revision, evidence_ids),
    ), "revise", "dream explicit source correction")
