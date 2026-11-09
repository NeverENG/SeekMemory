"""Bounded read-only impact inspection before any Dream hierarchy correction.

Dream 纠错前的有界只读影响检查；不推断正确结论，也不提交版本或树边。
"""
from __future__ import annotations

from dataclasses import dataclass

from .ports import DreamImpactStore, SourceStore

try:
    from ..core.domain.memory.artifact import Artifact
    from ..core.port.tree import TreeEdgeReader
except ImportError:
    from core.domain.memory.artifact import Artifact
    from core.port.tree import TreeEdgeReader


@dataclass(frozen=True)
class CorrectionImpact:
    """A provisional dependency view, never a write authorization / 临时依赖视图，不能充当写入授权。"""

    affected_ids: tuple[str, ...]
    blockers: tuple[str, ...]
    visits: int
    truncated: bool


def inspect_correction_impact(
    artifacts: DreamImpactStore,
    sources: SourceStore,
    child_id: str,
    *,
    max_depth: int = 3,
    max_visits: int = 32,
    max_parents: int = 8,
    max_sources: int = 16,
) -> CorrectionImpact:
    """Compare raw edges with current reverse lineage, following only corroborated paths.

    Examine two independent dependency records per node. Any mismatch, missing
    evidence, cycle or exhausted budget blocks later automatic reconciliation.
    No memory text or Source body is included in the returned report.

    比较每个节点的原始边及当前反向血缘；仅沿双方一致的路径继续，异常一律暂缓。
    """
    if not (1 <= max_depth <= 6 and 1 <= max_visits <= 64
            and 1 <= max_parents <= 8 and 1 <= max_sources <= 32):
        raise ValueError("impact limits out of bounds")
    root = artifacts.get(child_id) if child_id else None
    if root is None or root.header.family != "memory" or root.header.state != "active":
        return CorrectionImpact((), ("invalid_child",), 0, False)

    blockers: set[str] = set()
    if not root.header.subject_id:
        blockers.add("missing_identity")
    affected: list[str] = []
    valid_links: dict[str, set[str]] = {}
    seen = {child_id}
    queue: list[tuple[Artifact, int, frozenset[str]]] = [(root, 0, frozenset({child_id}))]
    visits = 0

    def evidence_ok(art: Artifact) -> bool:
        ids = art.header.lineage.sources
        if not ids or len(ids) > max_sources:
            blockers.add("evidence_limit" if len(ids) > max_sources else "missing_evidence")
            return False
        committed = artifacts.current_evidence_ids(art.header.id, max_sources + 1)
        if len(committed) > max_sources:
            blockers.add("evidence_limit")
            return False
        if set(committed) != set(ids):
            blockers.add("missing_version_evidence")
            return False
        evidence = sources.sources_by_ids(list(ids))
        if len(evidence) != len(set(ids)):
            blockers.add("missing_evidence")
            return False
        if any(source.role == "user" and source.speaker_id != root.header.subject_id
               for source in evidence.values()):
            blockers.add("evidence_identity")
            return False
        return True

    if not evidence_ok(root) or "missing_identity" in blockers:
        return CorrectionImpact((), tuple(sorted(blockers)), 0, False)
    while queue and visits < max_visits:
        current, depth, path = queue.pop(0)
        visits += 1
        raw_edges = artifacts.tree_parents(current.header.id, max_parents + 1)
        raw_lineage = artifacts.active_dependents(current.header.id, max_parents + 1)
        if len(raw_edges) > max_parents or len(raw_lineage) > max_parents:
            blockers.add("branch_limit")
        edges = set(raw_edges[:max_parents])
        lineage = set(raw_lineage[:max_parents])
        if depth == 0 and not edges and not lineage:
            blockers.add("no_dependents")
        for parent_id in sorted(edges | lineage):
            if parent_id not in edges:
                blockers.add("lineage_without_edge")
            if parent_id not in lineage:
                blockers.add("edge_without_lineage")
            parent = artifacts.get(parent_id)
            if parent is None:
                blockers.add("missing_parent")
                continue
            if parent.header.family != "memory" or parent.header.state != "active":
                blockers.add("stale_edge")
                continue
            if (parent.header.subject_id, parent.header.scope, parent.header.shareable) != (
                root.header.subject_id, root.header.scope, root.header.shareable
            ):
                blockers.add("identity_mismatch")
                continue
            if parent_id in lineage and current.header.id not in parent.header.lineage.derived_from:
                blockers.add("invalid_lineage")
                continue
            if not evidence_ok(parent):
                continue
            if not set(current.header.lineage.sources).intersection(parent.header.lineage.sources):
                blockers.add("evidence_mismatch")
                continue
            if parent_id not in edges or parent_id not in lineage:
                continue
            valid_links.setdefault(current.header.id, set()).add(parent_id)
            if parent_id in path:
                blockers.add("cycle")
                continue
            if depth >= max_depth:
                blockers.add("depth_limit")
                continue
            if parent_id not in seen:
                seen.add(parent_id)
                affected.append(parent_id)
                queue.append((parent, depth + 1, path | {parent_id}))
    if queue:
        blockers.add("visit_limit")
    # A shared ancestor may be reached through two paths; one BFS path alone
    # cannot detect a cycle whose back-edge follows the other path.
    visiting: set[str] = set()
    completed: set[str] = set()

    def has_cycle(node_id: str) -> bool:
        if node_id in visiting:
            return True
        if node_id in completed:
            return False
        visiting.add(node_id)
        if any(has_cycle(parent_id) for parent_id in sorted(valid_links.get(node_id, ()))):
            return True
        visiting.remove(node_id)
        completed.add(node_id)
        return False

    if has_cycle(child_id):
        blockers.add("cycle")
    return CorrectionImpact(
        tuple(affected), tuple(sorted(blockers)), visits,
        bool(blockers & {"depth_limit", "visit_limit", "branch_limit"}),
    )
