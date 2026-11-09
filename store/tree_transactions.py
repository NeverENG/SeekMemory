"""One SQLite transaction for evidence-backed Artifact heads and tree projection.

证据版本、树投影和无正文操作日志在同一 SQLite 事务内提交。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from hashlib import sha256

try:
    from ..core.domain.memory.tree_change import TreeChange, TreeLink
    from ..core.domain.memory.versioning import VersionError
except ImportError:
    from core.domain.memory.tree_change import TreeChange, TreeLink
    from core.domain.memory.versioning import VersionError

from .sqlite import now_iso
from .tree_validation import TreeValidation


def _digest(change: TreeChange) -> str:
    # The digest covers payloads, but no plaintext is persisted in the log.
    encoded = json.dumps(
        asdict(change),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


class TreeTransactions(TreeValidation):
    """Mixin for ArtifactRepository: the borrowed connection is the transaction owner."""

    def tree_operation_done(self, operation_id: str) -> bool:
        """Check durable tree-operation identity without reading text or plans."""
        return (
            self.conn.execute(
                "SELECT 1 FROM tree_change_log WHERE operation_id = ?",
                (operation_id,),
            ).fetchone()
            is not None
        )

    def commit_tree_change(self, change: TreeChange) -> bool:
        """Return True on a new commit, False for the same durable operation; conflicts raise.

        Explicit BEGIN IMMEDIATE guarantees snapshots, CAS, edges, ledger and log share
        one transaction; a failed write leaves no partially published projection.
        """
        if not re.fullmatch(r"[A-Za-z0-9_:-]{1,128}", change.operation_id):
            raise ValueError("invalid tree operation ID")
        if change.op not in ("create", "revise", "merge", "forget", "promote"):
            raise ValueError("invalid tree operation")
        if not 1 <= len(change.writes) <= 33 or not 1 <= len(change.observed) <= 64:
            raise ValueError("tree change limit exceeded")
        digest = _digest(change)
        if self.conn.in_transaction:
            raise RuntimeError("tree change requires its own transaction")
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            existing = self.conn.execute(
                "SELECT plan_hash FROM tree_change_log WHERE operation_id = ?",
                (change.operation_id,),
            ).fetchone()
            if existing is not None:
                if existing["plan_hash"] != digest:
                    raise VersionError("tree operation ID conflict")
                self.conn.commit()
                return False
            self._check_tree_change(change)
            for write in change.writes:
                self._commit_conn(
                    write.artifact,
                    expected_revision=write.expected_revision,
                    op=change.op,
                    reason=change.reason,
                    source_ids=write.source_ids,
                )
            for child_id, before in change.edges_before:
                for link in before:
                    self.conn.execute(
                        "DELETE FROM edges WHERE src = ? AND dst = ? AND kind = ?",
                        (link.parent, child_id, "tree_child:" + link.parent),
                    )
            for _, after in change.edges_after:
                for link in after:
                    self.conn.execute(
                        "INSERT INTO edges(src, dst, kind, weight) VALUES(?, ?, ?, ?)",
                        (
                            link.parent,
                            link.child,
                            "tree_child:" + link.parent,
                            link.weight,
                        ),
                    )
            summary = json.dumps(
                [
                    (
                        w.artifact.header.id,
                        w.expected_revision,
                        w.artifact.header.revision,
                    )
                    for w in change.writes
                ],
                separators=(",", ":"),
            )

            def links(snapshots: tuple[tuple[str, tuple[TreeLink, ...]], ...]) -> str:
                return json.dumps(
                    [
                        (
                            child,
                            [(link.parent, link.child, link.weight) for link in edges],
                        )
                        for child, edges in snapshots
                    ],
                    separators=(",", ":"),
                )

            self.conn.execute(
                "INSERT INTO tree_change_log(operation_id, plan_hash, revisions, edges_before, "
                "edges_after, at) VALUES(?, ?, ?, ?, ?, ?)",
                (
                    change.operation_id,
                    digest,
                    summary,
                    links(change.edges_before),
                    links(change.edges_after),
                    now_iso(),
                ),
            )
            self.conn.commit()
            return True
        except BaseException:
            self.conn.rollback()
            raise
