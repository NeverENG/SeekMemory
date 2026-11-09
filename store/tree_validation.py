"""Validate bounded tree snapshots, current evidence and acyclicity in a transaction.

在调用方事务内验证树快照、证据、身份与环约束。
"""

from __future__ import annotations

import math

try:
    from ..core.domain.memory.tree_change import TreeChange, TreeLink
    from ..core.domain.memory.versioning import VersionError
except ImportError:
    from core.domain.memory.tree_change import TreeChange, TreeLink
    from core.domain.memory.versioning import VersionError


class TreeValidation:
    """Validation SQL reuses the transaction owner's borrowed connection."""

    def tree_snapshot(self, child_id: str) -> tuple[TreeLink, ...]:
        """Read the entire inbound tree projection, including malformed old edges."""
        rows = self.conn.execute(
            "SELECT src, dst, kind, weight FROM edges WHERE dst = ? "
            "AND kind LIKE 'tree_child:%' ORDER BY src, dst, kind LIMIT 9",
            (child_id,),
        ).fetchall()
        # Reject malformed kind rather than reinterpret a legacy row as a valid link.
        if any(row["kind"] != "tree_child:" + row["src"] for row in rows):
            raise ValueError("malformed tree edge")
        if len(rows) > 8:
            raise ValueError("tree parent limit exceeded")
        return tuple(
            TreeLink(str(r["src"]), str(r["dst"]), float(r["weight"])) for r in rows
        )

    def _check_tree_change(self, change: TreeChange) -> None:
        writes = {w.artifact.header.id: w for w in change.writes}
        heads = dict(change.observed)
        before = dict(change.edges_before)
        after = dict(change.edges_after)
        if (
            len(writes) != len(change.writes)
            or len(heads) != len(change.observed)
            or len(before) != len(change.edges_before)
            or len(after) != len(change.edges_after)
            or set(before) != set(after)
            or not before
            or len(before) > 32
        ):
            raise ValueError("invalid tree change coverage")
        if any(
            key not in heads or heads[key] != write.expected_revision
            for key, write in writes.items()
        ):
            raise ValueError("tree revision not observed")
        for node_id, revision in heads.items():
            row = self.conn.execute(
                "SELECT revision FROM nodes WHERE id = ?", (node_id,)
            ).fetchone()
            if (int(row["revision"]) if row else 0) != revision:
                raise VersionError("tree head conflict")
        for child_id, snapshot in change.edges_before:
            if child_id not in writes:
                raise ValueError("affected child must be revised")
            if snapshot != self.tree_snapshot(child_id):
                raise VersionError("tree edge snapshot conflict")
            if len(after[child_id]) > 8:
                raise ValueError("tree parent limit exceeded")
        all_links = (
            *[link for edges in before.values() for link in edges],
            *[link for edges in after.values() for link in edges],
        )
        if any(
            link.child != child_id
            or link.parent == child_id
            or not link.parent
            or not math.isfinite(link.weight)
            or link.weight <= 0
            for child_id, edges in (*change.edges_before, *change.edges_after)
            for link in edges
        ):
            raise ValueError("invalid tree link")
        for edges in (*before.values(), *after.values()):
            if len({link.parent for link in edges}) != len(edges):
                raise ValueError("duplicate tree parent")
        for link in all_links:
            if link.parent not in heads or link.child not in heads:
                raise ValueError("tree endpoint not observed")
            parent = (
                writes[link.parent].artifact
                if link.parent in writes
                else self.get(link.parent)
            )
            child = (
                writes[link.child].artifact
                if link.child in writes
                else self.get(link.child)
            )
            if (
                parent is None
                or child is None
                or parent.header.family != "memory"
                or child.header.family != "memory"
                or (
                    parent.header.subject_id,
                    parent.header.scope,
                    parent.header.shareable,
                )
                != (child.header.subject_id, child.header.scope, child.header.shareable)
            ):
                raise ValueError("tree identity or scope conflict")
            if link in after.get(link.child, ()) and (
                parent.header.state != "active" or child.header.state != "active"
            ):
                raise ValueError("inactive tree endpoint")
        # An existing parent conclusion cannot remain active and stale after its child changes.
        for child_id, old_links in before.items():
            if (
                heads[child_id] > 0
                and old_links
                and any(link.parent not in writes for link in old_links)
            ):
                raise ValueError("unreviewed parent conclusion")
        for node_id, revision in heads.items():
            art = writes[node_id].artifact if node_id in writes else self.get(node_id)
            if art is None:
                if revision != 0:
                    raise ValueError("missing tree endpoint")
                continue
            evidence = (
                writes[node_id].source_ids
                if node_id in writes
                else tuple(self.current_evidence_ids(node_id, 129))
            )
            if (
                not evidence
                or len(evidence) > 128
                or set(evidence) != set(art.header.lineage.sources)
            ):
                raise ValueError("tree endpoint lacks current Source evidence")
            marks = ",".join("?" for _ in evidence)
            sources = self.conn.execute(
                f"SELECT role, json_extract(flags, '$.speaker_id') AS speaker "
                f"FROM sources WHERE id IN ({marks})",
                evidence,
            ).fetchall()
            if len(sources) != len(set(evidence)):
                raise ValueError("tree Source evidence missing")
            if art.header.subject_id and any(
                row["role"] == "user" and row["speaker"] != art.header.subject_id
                for row in sources
            ):
                raise ValueError("tree Source subject mismatch")
        self._check_tree_cycles(after)

    def _check_tree_cycles(self, after: dict[str, tuple[TreeLink, ...]]) -> None:
        """Reject cycles or truncated proofs in the proposed current projection."""
        additions: dict[str, set[str]] = {}
        for edges in after.values():
            for link in edges:
                additions.setdefault(link.parent, set()).add(link.child)
        for parent, children in additions.items():
            for child in children:
                seen, frontier = {child}, [child]
                for depth in range(9):
                    upcoming = []
                    for node in frontier:
                        rows = self.conn.execute(
                            "SELECT dst FROM edges WHERE src = ? AND kind = 'tree_child:' || src "
                            "ORDER BY dst LIMIT 65",
                            (node,),
                        ).fetchall()
                        if len(rows) > 64:
                            raise ValueError("tree cycle check limit exceeded")
                        destinations = set(additions.get(node, ()))
                        for row in rows:
                            dst = str(row["dst"])
                            if dst not in after or any(
                                item.parent == node for item in after[dst]
                            ):
                                destinations.add(dst)
                        for dst in destinations:
                            if dst == parent:
                                raise ValueError("tree cycle")
                            if dst not in seen:
                                seen.add(dst)
                                upcoming.append(dst)
                    if len(seen) > 64:
                        raise ValueError("tree cycle check limit exceeded")
                    if not upcoming:
                        break
                    if depth == 8:
                        raise ValueError("tree cycle check depth exceeded")
                    frontier = upcoming
