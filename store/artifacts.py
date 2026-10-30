"""Read and atomically commit Artifact revisions through a borrowed connection; never update cache.

通过借用的连接读取并原子提交记忆版本，不更新缓存。
"""

from __future__ import annotations

import json

try:
    from .artifact_sql import SELECT_SQL, UPSERT_SQL
    from .artifact_codec import (
        node_values,
        payload_blob,
        row_to_artifact,
        stored_header,
    )
    from .ledger import append_ledger_conn
    from .sqlite import SqliteRepository, dump_json, now_iso
except ImportError:
    from artifact_sql import SELECT_SQL, UPSERT_SQL
    from artifact_codec import (
        node_values,
        payload_blob,
        row_to_artifact,
        stored_header,
    )
    from ledger import append_ledger_conn
    from sqlite import SqliteRepository, dump_json, now_iso

try:
    from ..core.domain.memory.graph import ArtifactEdge
    from ..core.domain.memory.artifact import Artifact
    from ..core.domain.memory.versioning import StateEvent, VersionError, assert_next_revision
except ImportError:
    from core.domain.memory.graph import ArtifactEdge
    from core.domain.memory.artifact import Artifact
    from core.domain.memory.versioning import StateEvent, VersionError, assert_next_revision


_COMMIT_OPERATIONS = frozenset({
    "create", "revise", "reinforce", "deliver", "merge", "forget", "promote",
})


class ArtifactRepository(SqliteRepository):
    """Own current memories, versions, evidence, graph writes and atomic ledger updates / 管理当前记忆、版本、证据、图写入及原子账本更新。"""

    def upsert(self, art: Artifact) -> None:
        """Seed benchmark data without the production CAS/ledger contract; never use in production / 填充跑分样本，不提供生产预期版本与账本契约，不得用于生产。"""
        header, now = art.header, now_iso()
        content, blob = payload_blob(art.payload)
        args = node_values(header, art.payload, now, blob)
        header_blob = stored_header(header)
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO blobs(hash, content, at) VALUES(?, ?, ?)",
                (blob, content, now),
            )
            self.conn.execute(UPSERT_SQL, args)
            self.conn.execute(
                "INSERT OR IGNORE INTO versions(entity, revision, blob, header, at) "
                "VALUES(?, ?, ?, ?, ?)",
                (header.id, int(header.revision), blob, header_blob, now),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO artifact_versions("
                "entity, revision, op, blob, header, at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (header.id, int(header.revision), "upsert", blob, header_blob, now),
            )

    def count(self, family: str | None = None) -> int:
        """Count matching stored memories without loading payloads / 统计匹配的存储记忆，不加载正文。"""
        if family is None:
            row = self.conn.execute("SELECT COUNT(*) AS c FROM nodes").fetchone()
            return int(row["c"]) if row is not None else 0
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM nodes WHERE family = ?",
            (family,),
        ).fetchone()
        return int(row["c"]) if row is not None else 0

    def commit(
        self,
        art: Artifact,
        *,
        expected_revision: int,
        op: str,
        reason: str = "",
        source_ids: tuple[str, ...] = (),
        state_events: tuple[StateEvent, ...] = (),
    ) -> None:
        """Commit one expected revision, evidence, events and ledger atomically; errors roll back / 原子提交一个预期版本、证据、事件及账本，错误时回滚。"""
        if op not in _COMMIT_OPERATIONS:
            raise ValueError(f"unknown commit op: {op}")
        with self.conn:
            self._commit_conn(
                art,
                expected_revision=expected_revision,
                op=op,
                reason=reason,
                source_ids=source_ids,
                state_events=state_events,
            )

    def commit_many(
        self,
        writes: list[tuple[Artifact, int, tuple[str, ...]]],
        *,
        op: str,
        reason: str = "",
    ) -> None:
        """Commit the whole supplied revision group in one transaction; any failure rolls it back / 在一个事务中提交给定版本组，任一失败则整组回滚。"""
        if not writes:
            return
        if op not in _COMMIT_OPERATIONS:
            raise ValueError(f"unknown commit op: {op}")
        with self.conn:
            for art, expected_revision, source_ids in writes:
                self._commit_conn(
                    art,
                    expected_revision=expected_revision,
                    op=op,
                    reason=reason,
                    source_ids=source_ids,
                )

    def history(self, node_id: str) -> list[dict]:
        """Read version payloads in revision order, skipping malformed old rows / 按版本顺序读取历史内容，跳过格式错误的旧行。"""
        rows = self.conn.execute(
            "SELECT v.revision, v.op, v.at, b.content FROM artifact_versions v "
            "JOIN blobs b ON v.blob = b.hash WHERE v.entity = ? "
            "ORDER BY v.revision ASC",
            (node_id,),
        ).fetchall()
        out = []
        for revision, op, at, content in rows:
            try:
                payload = json.loads(content)
            except Exception:  # noqa: BLE001 - Skip malformed legacy rows / 跳过格式错误的旧行。
                continue
            out.append(
                {
                    "revision": int(revision),
                    "op": str(op),
                    "at": str(at),
                    "payload": payload,
                }
            )
        return out

    def get(self, node_id: str) -> Artifact | None:
        """Read the current memory or None / 读取当前记忆，不存在时返回空。"""
        row = self.conn.execute(
            SELECT_SQL + " WHERE n.id = ?", (node_id,)
        ).fetchone()
        return row_to_artifact(row)

    def by_source_ids(self, source_ids: list[str]) -> list[Artifact]:
        """Read active current versions with matching current-version evidence / 读取具有匹配当前版本证据的有效记忆。"""
        ids: list[str] = []
        for value in source_ids:
            text = str(value or "").strip()
            if text and text not in ids:
                ids.append(text)
        if not ids:
            return []
        marks = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            "SELECT DISTINCT n.*, b.content AS blob_content FROM nodes n "
            "LEFT JOIN blobs b ON b.hash = n.blob "
            "JOIN artifact_evidence ae ON ae.entity = n.id "
            "AND ae.revision = n.revision "
            f"WHERE n.state = 'active' AND ae.source IN ({marks}) "
            "ORDER BY n.created_at, n.id",
            ids,
        ).fetchall()
        return [art for art in map(row_to_artifact, rows) if art is not None]

    def list(
        self, family: str | None = None, state: str | None = None
    ) -> list[Artifact]:
        """Read current memories using optional family/state filters / 按可选类型及状态读取当前记忆。"""
        sql, args = SELECT_SQL, []
        for column, value in (("family", family), ("state", state)):
            if value is not None:
                sql += (" WHERE " if not args else " AND ") + f"n.{column} = ?"
                args.append(value)
        rows = self.conn.execute(sql + " ORDER BY n.created_at, n.id", args).fetchall()
        return [art for art in map(row_to_artifact, rows) if art is not None]

    def set_parent(self, node_id: str, parent_id: str | None) -> None:
        """Write only the compatibility parent column; do not maintain graph edges or version snapshots / 仅写入兼容父字段，不维护图连接或版本快照。"""
        with self.conn:
            self.conn.execute(
                "UPDATE nodes SET parent = ?, updated_at = ? WHERE id = ?",
                (parent_id, now_iso(), str(node_id)),
            )

    def list_recent(self, limit: int) -> list[Artifact]:
        """Read a bounded recent-memory snapshot before decoding payloads / 先限量读取近期记忆快照，再解析正文。"""
        if not 1 <= limit <= 120:
            raise ValueError("recent artifact limit must be between 1 and 120")
        # Bound headers before decoding blobs / 在解析正文前限制头部数量。
        rows = self.conn.execute(
            "WITH recent AS (SELECT * FROM nodes ORDER BY updated_at DESC, id DESC LIMIT ?) "
            "SELECT n.*, b.content AS blob_content FROM recent n "
            "LEFT JOIN blobs b ON b.hash = n.blob ORDER BY n.updated_at DESC, n.id DESC",
            (limit,),
        ).fetchall()
        return [art for art in map(row_to_artifact, rows) if art is not None]

    def list_impressions(self, limit: int, offset: int = 0) -> list[Artifact]:
        """Read one deterministic impression page grouped by subject and scope / 按主体和范围分组，确定性读取一页印象。"""
        if not 1 <= limit <= 100 or not 0 <= offset <= 100000:
            raise ValueError("impression page parameters are out of bounds")
        rows = self.conn.execute(
            "WITH ranked AS ("
            "SELECT n.*, b.content AS blob_content, "
            "ROW_NUMBER() OVER (PARTITION BY n.subject_id, n.scope "
            "ORDER BY n.updated_at DESC, n.revision DESC, n.id DESC) AS rn "
            "FROM nodes n LEFT JOIN blobs b ON b.hash = n.blob "
            "WHERE n.family = 'memory' AND n.state = 'active' "
            "AND n.subject_id IS NOT NULL AND n.subject_id != '' "
            "AND json_extract(b.content, '$.level') = 'impression') "
            "SELECT * FROM ranked WHERE rn = 1 "
            "ORDER BY subject_id, scope, updated_at DESC, id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [art for art in map(row_to_artifact, rows) if art is not None]

    def count_impressions(self) -> int:
        """Count distinct subject/scope impression groups / 统计不同主体与范围的印象组。"""
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM ("
            "SELECT n.subject_id, n.scope FROM nodes n "
            "LEFT JOIN blobs b ON b.hash = n.blob "
            "WHERE n.family = 'memory' AND n.state = 'active' "
            "AND n.subject_id IS NOT NULL AND n.subject_id != '' "
            "AND json_extract(b.content, '$.level') = 'impression' "
            "GROUP BY n.subject_id, n.scope)"
        ).fetchone()
        return int(row["c"]) if row is not None else 0

    def edges_between(self, node_ids: list[str], limit: int) -> list[ArtifactEdge]:
        """Read bounded edges within supplied IDs; preserve stored direction / 限量读取给定编号之间的连接，保留存储方向。"""
        ids = sorted(set(node_ids))
        if len(ids) > 120 or not 1 <= limit <= 240:
            raise ValueError("graph edge query exceeds snapshot bounds")
        if not ids:
            return []
        marks = ",".join("(?)" for _ in ids)
        # Unary + avoids N*N indexed pair probes; text membership stays unchanged.
        # 一元加号避免逐对索引探测；文本类型的成员判断不变。
        rows = self.conn.execute(
            f"WITH selected(id) AS (VALUES {marks}) "
            "SELECT e.src, e.dst, e.kind, e.weight FROM edges e "
            "WHERE e.src IN (SELECT id FROM selected) "
            "AND +e.dst IN (SELECT id FROM selected) "
            "AND e.src != e.dst ORDER BY e.src, e.dst, e.kind LIMIT ?",
            [*ids, limit],
        ).fetchall()
        return [ArtifactEdge(str(r["src"]), str(r["dst"]), str(r["kind"]), float(r["weight"])) for r in rows]

    def add_edge(self, src: str, dst: str, kind: str, weight: float) -> None:
        """Upsert one graph edge in its own transaction / 在独立事务中写入或更新一条图连接。"""
        with self.conn:
            self.conn.execute(
                "INSERT INTO edges(src, dst, kind, weight) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(src, dst, kind) DO UPDATE SET weight=excluded.weight",
                (src, dst, kind, float(weight)),
            )

    def edges_of(self, node_id: str) -> list[tuple[str, str, float]]:
        """Read both endpoints as other-ID, kind and weight; omit direction / 读取两端连接的另一端编号、类型及权重，不包含方向。"""
        rows = self.conn.execute(
            "SELECT dst AS other, kind, weight FROM edges WHERE src = ? "
            "UNION SELECT src AS other, kind, weight FROM edges WHERE dst = ?",
            (node_id, node_id),
        ).fetchall()
        return [(str(r["other"]), str(r["kind"]), float(r["weight"])) for r in rows]

    def inspect_record(self, node_id: str) -> dict:
        """Read stored version headers and available immutable evidence without fabrication / 读取已存版本头部及可用不可变证据，不补造缺失信息。"""
        versions = self.conn.execute(
            "SELECT v.revision, v.op, v.at, v.blob, v.header, b.content "
            "FROM artifact_versions v LEFT JOIN blobs b ON b.hash = v.blob "
            "WHERE v.entity = ? ORDER BY v.revision DESC",
            (node_id,),
        ).fetchall()
        sources = self.conn.execute(
            "SELECT s.id, s.umo, s.at, s.role, s.blob, s.flags, b.content AS text "
            "FROM sources s LEFT JOIN blobs b ON b.hash = s.blob "
            "WHERE s.id IN (SELECT source FROM evidence WHERE node = ? "
            "UNION SELECT source FROM artifact_evidence WHERE entity = ?) "
            "ORDER BY s.at",
            (node_id, node_id),
        ).fetchall()
        return {
            "versions": [dict(row) for row in versions],
            "sources": [dict(row) for row in sources],
        }

    def _commit_conn(
        self,
        art: Artifact,
        *,
        expected_revision: int,
        op: str,
        reason: str,
        source_ids: tuple[str, ...] = (),
        state_events: tuple[StateEvent, ...] = (),
    ) -> None:
        """Write one revision inside the caller-owned transaction; never commit or update cache here / 在调用方事务中写入一个版本，此处不独立提交或更新缓存。"""
        header = art.header
        now = now_iso()
        row = self.conn.execute(
            "SELECT revision FROM nodes WHERE id = ?", (header.id,)
        ).fetchone()
        current = int(row["revision"]) if row is not None else 0
        if current != int(expected_revision):
            raise VersionError(
                f"revision conflict: expected {expected_revision}, current {current}"
            )
        previous = self.get(header.id) if current else None
        assert_next_revision(previous, art)
        content, blob = payload_blob(art.payload)
        args = node_values(header, art.payload, now, blob)
        header_blob = stored_header(header)
        self.conn.execute(
            "INSERT OR IGNORE INTO blobs(hash, content, at) VALUES(?, ?, ?)",
            (blob, content, now),
        )
        self.conn.execute(UPSERT_SQL, args)
        self.conn.execute(
            "INSERT INTO versions(entity, revision, blob, header, at) "
            "VALUES(?, ?, ?, ?, ?)",
            (header.id, int(header.revision), blob, header_blob, now),
        )
        self.conn.execute(
            "INSERT INTO artifact_versions(entity, revision, op, blob, header, at) "
            "VALUES(?, ?, ?, ?, ?, ?)",
            (header.id, int(header.revision), op, blob, header_blob, now),
        )
        for source_id in source_ids:
            self.conn.execute(
                "INSERT OR IGNORE INTO artifact_evidence(entity, revision, source) "
                "VALUES(?, ?, ?)",
                (header.id, int(header.revision), str(source_id)),
            )
        for event in state_events:
            event.validate()
            self.conn.execute(
                "INSERT OR IGNORE INTO state_events("
                "id, entity, revision_seen, op, delta, at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.entity_id,
                    event.revision_seen,
                    event.op,
                    dump_json(event.delta),
                    event.at or now,
                ),
            )
        before = str(current) if current else None
        append_ledger_conn(
            self.conn,
            op,
            header.id,
            before,
            str(header.revision),
            reason,
            now,
        )
