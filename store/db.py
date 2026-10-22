"""SQLite 持久化层：Artifact 与数据行的双向转换、追加日志写入。

这是整个项目唯一写 SQL 的文件；异常交给调用方 fail-open 处理。
"""

from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

try:  # 作为 astrbot 插件包的一部分导入
    from ..app.contracts import ExtractionState
    from ..core.artifact import Artifact, Header, Lineage, Strength, TimeSpan
    from ..core.source import Source
    from ..core.versioning import StateEvent, VersionError, assert_next_revision
except ImportError:  # 作为顶层 store 包导入（脚本 / 测试）
    from app.contracts import ExtractionState
    from core.artifact import Artifact, Header, Lineage, Strength, TimeSpan
    from core.source import Source
    from core.versioning import StateEvent, VersionError, assert_next_revision

SCHEMA_PATH = Path(__file__).with_name("schema.sql")
_SELECT = (
    "SELECT n.*, b.content AS blob_content FROM nodes n "
    "LEFT JOIN blobs b ON b.hash = n.blob"
)
_UPSERT = (
    "INSERT INTO nodes(id, family, level, parent, blob, state, scope, strength, time, "
    "said_by, shareable, created_at, updated_at, revision, lineage, subject_id) "
    "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
    "family=excluded.family, level=excluded.level, "
    "parent=COALESCE(excluded.parent, nodes.parent), blob=excluded.blob, "
    "state=excluded.state, scope=excluded.scope, strength=excluded.strength, "
    "time=excluded.time, said_by=excluded.said_by, shareable=excluded.shareable, "
    "revision=excluded.revision, lineage=excluded.lineage, subject_id=excluded.subject_id, "
    "updated_at=excluded.updated_at, "
    "created_at=CASE WHEN nodes.created_at = '' THEN excluded.created_at "
    "ELSE nodes.created_at END"
)


def _now() -> str:
    """当前本地时间，精确到秒。"""
    return datetime.datetime.now().isoformat(timespec="seconds")


EXTRACTION_MAX_ATTEMPTS = 5
_EXTRACTION_BACKOFF_BASE_SECONDS = 30
_EXTRACTION_BACKOFF_CAP_SECONDS = 3600


def _backoff_at(now: str, attempt: int) -> str:
    """Return the next retry instant for a bounded exponential backoff."""
    base = _parse_time(now) or datetime.datetime.now()
    delay = min(
        _EXTRACTION_BACKOFF_CAP_SECONDS,
        _EXTRACTION_BACKOFF_BASE_SECONDS * 2 ** max(0, attempt - 1),
    )
    return (base + datetime.timedelta(seconds=delay)).isoformat(timespec="seconds")


def _parse_time(value: str) -> datetime.datetime | None:
    """Parse an ISO timestamp without making malformed legacy rows fatal."""
    try:
        return datetime.datetime.fromisoformat(str(value or "").strip())
    except (TypeError, ValueError):
        return None


def _age_seconds(value: datetime.datetime | None, now: datetime.datetime) -> float:
    """Return a non-negative age even when legacy times use different tz awareness."""
    if value is None:
        return 0.0
    try:
        return max(0.0, now.timestamp() - value.timestamp())
    except (OSError, OverflowError, ValueError):
        return 0.0


def _dump(value: Any) -> str:
    """把 dataclass / dict / 元组序列化成稳定的 JSON 文本。"""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _loads(raw: Any) -> dict[str, Any]:
    """容错地把 TEXT 列读成 dict；坏数据退回空 dict。"""
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _pick(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """只保留 cls 的 dataclass 字段，容忍多出来的键。"""
    names = {f.name for f in dataclasses.fields(cls)}
    return {k: v for k, v in data.items() if k in names}


def chain_payload(
    at: str, op: str, entity: str, before: str | None, after: str | None, reason: str
) -> str:
    """把一条日志的业务字段拼成哈希输入；顺序固定，便于重算。"""
    return json.dumps(
        [at, op, entity, before, after, reason],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def chain_hash(prev_hash: str, payload: str) -> str:
    """哈希链单步：sha256(prev_hash + payload) 取前 16 位。"""
    return hashlib.sha256((prev_hash + payload).encode("utf-8")).hexdigest()[:16]


class DB:
    """SQLite 门面：节点、边、来源、证据与日志。"""

    def __init__(self, path: str) -> None:
        """打开数据库、设置 WAL，并保证表结构存在。"""
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._migrate()

    def _migrate(self) -> None:
        cols = {r[1] for r in self.conn.execute("PRAGMA table_info(nodes)")}
        state_cols = {
            r[1] for r in self.conn.execute("PRAGMA table_info(extraction_state)")
        }
        with self.conn:
            if "subject_id" not in cols:
                self.conn.execute(
                    "ALTER TABLE nodes ADD COLUMN subject_id TEXT NOT NULL DEFAULT ''"
                )
            if state_cols and "next_attempt_at" not in state_cols:
                self.conn.execute(
                    "ALTER TABLE extraction_state ADD COLUMN "
                    "next_attempt_at TEXT NOT NULL DEFAULT ''"
                )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_nodes_subject ON nodes(subject_id)"
            )

    def upsert(self, art: Artifact) -> None:
        h, now = art.header, _now()
        content = _dump(art.payload)
        blob = hashlib.sha256(content.encode("utf-8")).hexdigest()
        level, parent = art.payload.get("level"), art.payload.get("parent")
        args = (
            h.id,
            h.family,
            level if isinstance(level, str) else None,
            parent if isinstance(parent, str) else None,
            blob,
            h.state,
            h.scope,
            _dump(h.strength),
            _dump(h.time),
            h.said_by,
            h.shareable,
            h.time.created or now,
            h.time.updated or now,
            int(h.revision),
            _dump(h.lineage),
            h.subject_id,
        )
        header = _dump(
            {
                "state": h.state,
                "scope": h.scope,
                "strength": _dump(h.strength),
                "time": _dump(h.time),
                "said_by": h.said_by,
                "revision": int(h.revision),
                "lineage": _dump(h.lineage),
                "subject_id": h.subject_id,
            }
        )
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO blobs(hash, content, at) VALUES(?, ?, ?)",
                (blob, content, now),
            )
            self.conn.execute(_UPSERT, args)
            self.conn.execute(
                "INSERT OR IGNORE INTO versions(entity, revision, blob, header, at) "
                "VALUES(?, ?, ?, ?, ?)",
                (h.id, int(h.revision), blob, header, now),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO artifact_versions(entity, revision, op, blob, header, at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (h.id, int(h.revision), "upsert", blob, header, now),
            )

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
        if op not in (
            "create",
            "revise",
            "reinforce",
            "deliver",
            "merge",
            "forget",
            "promote",
        ):
            raise ValueError(f"unknown commit op: {op}")
        self._commit_conn(
            art,
            expected_revision=expected_revision,
            op=op,
            reason=reason,
            source_ids=source_ids,
            state_events=state_events,
        )

    def history(self, node_id: str) -> list[dict]:
        """返回一条记忆的版本链（旧→新）：revision / at / payload。"""
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
            except Exception:  # noqa: BLE001 - 坏内容跳过，不拖垮整条链
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
        """按 id 取一条完整记忆；不存在或数据损坏时返回 None。"""
        row = self.conn.execute(_SELECT + " WHERE n.id = ?", (node_id,)).fetchone()
        return self._to_artifact(row)

    def list(
        self, family: str | None = None, state: str | None = None
    ) -> list[Artifact]:
        """按 family / state 过滤列出记忆，按创建时间排序。"""
        sql, args = _SELECT, []
        for column, value in (("family", family), ("state", state)):
            if value is not None:
                sql += (" WHERE " if not args else " AND ") + f"n.{column} = ?"
                args.append(value)
        rows = self.conn.execute(sql + " ORDER BY n.created_at, n.id", args).fetchall()
        return [art for art in map(self._to_artifact, rows) if art is not None]

    def source_umo(self, source_id: str) -> str:
        """按来源 id 取它所属的会话 umo；来源不存在时返回空串。"""
        row = self.conn.execute(
            "SELECT umo FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        return str(row["umo"]) if row is not None else ""

    def source_umos(self, source_ids: list[str]) -> dict[str, str]:
        ids = [str(x) for x in source_ids if x]
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            f"SELECT id, umo FROM sources WHERE id IN ({marks})", ids
        ).fetchall()
        return {str(row["id"]): str(row["umo"]) for row in rows}

    def set_parent(self, node_id: str, parent_id: str | None) -> None:
        """单独调整抽象树父子关系（CONTRACT 未列出，供 core/tree 使用）。"""
        with self.conn:
            self.conn.execute(
                "UPDATE nodes SET parent = ?, updated_at = ? WHERE id = ?",
                (parent_id, _now(), node_id),
            )

    def count(self, family: str | None = None) -> int:
        """统计节点行数，可按 family 过滤。"""
        row = self.conn.execute(
            "SELECT COUNT(*) AS c FROM nodes WHERE ? IS NULL OR family = ?",
            (family, family),
        ).fetchone()
        return int(row["c"]) if row is not None else 0

    def add_edge(self, src: str, dst: str, kind: str, weight: float) -> None:
        """新增或更新一条关系边。"""
        with self.conn:
            self.conn.execute(
                "INSERT INTO edges(src, dst, kind, weight) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(src, dst, kind) DO UPDATE SET weight=excluded.weight",
                (src, dst, kind, float(weight)),
            )

    def edges_of(self, node_id: str) -> list[tuple[str, str, float]]:
        """与该节点相连的边：(另一端 id, kind, weight)，双向都会返回。"""
        rows = self.conn.execute(
            "SELECT dst AS other, kind, weight FROM edges WHERE src = ? "
            "UNION SELECT src AS other, kind, weight FROM edges WHERE dst = ?",
            (node_id, node_id),
        ).fetchall()
        return [(str(r["other"]), str(r["kind"]), float(r["weight"])) for r in rows]

    def add_source(
        self, sid: str, umo: str, at: str, role: str, text: str, flags: dict[str, Any]
    ) -> None:
        """追加一条不可变的原始来源；同 id 只保留第一次写入。"""
        blob = hashlib.sha256(text.encode("utf-8")).hexdigest()
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO blobs(hash, content, at) VALUES(?, ?, ?)",
                (blob, text, at),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO sources(id, umo, at, role, blob, flags) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (sid, umo, at, role, blob, _dump(flags)),
            )

    def link_evidence(self, node_id: str, source_id: str) -> None:
        """把一条记忆挂到一条来源上；重复调用无副作用。"""
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO evidence(node, source) VALUES(?, ?)",
                (node_id, source_id),
            )

    def append_sources(self, sources: list[Source]) -> int:
        written = 0
        with self.conn:
            for src in sources:
                src.validate()
                blob = src.content_hash
                flags = {
                    "turn_id": src.turn_id,
                    "speaker_id": src.speaker_id,
                    "reply_to": src.reply_to,
                    "metadata": src.metadata,
                }
                self.conn.execute(
                    "INSERT OR IGNORE INTO blobs(hash, content, at) VALUES(?, ?, ?)",
                    (blob, src.text, src.at or _now()),
                )
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO sources(id, umo, at, role, blob, flags) "
                    "VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        src.id,
                        src.session_id,
                        src.at or _now(),
                        src.role,
                        blob,
                        _dump(flags),
                    ),
                )
                written += int(cur.rowcount or 0)
        return written

    def enqueue_extraction(
        self,
        source: Source,
        topic_id: str,
        created_at: str = "",
        *,
        deferred: bool = False,
    ) -> bool:
        """Atomically append a Source and its rebuildable extraction state.

        ``deferred`` parks the turn behind capacity admission; the Source row is
        still immutable truth and the row can be released later.
        """
        source.validate()
        flags = {
            "turn_id": source.turn_id,
            "speaker_id": source.speaker_id,
            "reply_to": source.reply_to,
            "metadata": source.metadata,
        }
        at = source.at or created_at or _now()
        state = "deferred" if deferred else "pending"
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO blobs(hash, content, at) VALUES(?, ?, ?)",
                (source.content_hash, source.text, at),
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO sources(id, umo, at, role, blob, flags) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (
                    source.id,
                    source.session_id,
                    at,
                    source.role,
                    source.content_hash,
                    _dump(flags),
                ),
            )
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO extraction_state("
                "source_id, turn_id, session_id, topic_id, state, attempts, "
                "next_attempt_at, last_error, created_at) "
                "VALUES(?, ?, ?, ?, ?, 0, '', '', ?)",
                (source.id, source.turn_id, source.session_id, topic_id, state, at),
            )
        return bool(cur.rowcount)

    def release_deferred(self, limit: int = 50) -> int:
        """Promote parked turns back into the queue once capacity has headroom."""
        limit = max(0, int(limit))
        if not limit:
            return 0
        with self.conn:
            cur = self.conn.execute(
                "UPDATE extraction_state SET state = 'pending', next_attempt_at = '' "
                "WHERE source_id IN ("
                "SELECT source_id FROM extraction_state WHERE state = 'deferred' "
                "ORDER BY created_at, source_id LIMIT ?)",
                (limit,),
            )
        return int(cur.rowcount or 0)

    def put_extraction_state(self, state: ExtractionState) -> bool:
        """Insert one queue state without duplicating Source content."""
        if not state.source_id or not state.session_id:
            raise ValueError("extraction state missing source or session")
        if state.state not in {"pending", "retrying", "deferred", "extracted"}:
            raise ValueError("unknown extraction state")
        source = self.conn.execute(
            "SELECT 1 FROM sources WHERE id = ?", (state.source_id,)
        ).fetchone()
        if source is None:
            raise ValueError("extraction source missing")
        with self.conn:
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO extraction_state("
                "source_id, turn_id, session_id, topic_id, state, attempts, "
                "next_attempt_at, last_error, created_at) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    state.source_id,
                    state.turn_id,
                    state.session_id,
                    state.topic_id,
                    state.state,
                    max(0, int(state.attempts)),
                    state.next_attempt_at,
                    state.last_error[:200],
                    state.created_at or _now(),
                ),
            )
        return bool(cur.rowcount)

    def pending_extractions(self, now: str = "") -> list[dict[str, Any]]:
        """Rebuild queued turns by joining extraction state with immutable Source.

        Args:
            now: 可选 ISO 时间；给出时跳过仍在重试退避窗口内的行。
        """
        rows = self.conn.execute(
            "SELECT e.source_id, e.turn_id, e.session_id, e.topic_id, e.state, "
            "e.attempts, e.next_attempt_at, e.last_error, e.created_at, "
            "s.role, s.at, s.flags, "
            "b.content AS text FROM extraction_state e "
            "JOIN sources s ON s.id = e.source_id "
            "JOIN blobs b ON b.hash = s.blob "
            "WHERE e.state IN ('pending', 'retrying') "
            "AND (? = '' OR e.next_attempt_at = '' OR e.next_attempt_at <= ?) "
            "ORDER BY e.created_at, e.source_id",
            (str(now or ""), str(now or "")),
        ).fetchall()
        out = []
        for row in rows:
            flags = _loads(row["flags"])
            out.append(
                {
                    "source_id": str(row["source_id"]),
                    "turn_id": str(row["turn_id"]),
                    "session_id": str(row["session_id"]),
                    "speaker_id": str(flags.get("speaker_id") or ""),
                    "role": str(row["role"]),
                    "text": str(row["text"]),
                    "at": str(row["at"]),
                    "topic_id": str(row["topic_id"]),
                    "state": str(row["state"]),
                    "attempts": int(row["attempts"]),
                    "next_attempt_at": str(row["next_attempt_at"]),
                    "last_error": str(row["last_error"]),
                    "created_at": str(row["created_at"]),
                }
            )
        return out

    def queue_counts(self) -> dict[str, int]:
        """Count extraction rows per lifecycle state without reading text."""
        counts = {
            "pending": 0,
            "retrying": 0,
            "deferred": 0,
            "extracted": 0,
            "dead": 0,
        }
        for row in self.conn.execute(
            "SELECT state, COUNT(*) AS rows FROM extraction_state GROUP BY state"
        ).fetchall():
            counts[str(row["state"])] = int(row["rows"])
        return counts

    def mark_extraction_succeeded(self, source_ids: list[str]) -> int:
        """Mark projection rows complete while retaining their Source and audit row."""
        ids = [str(value) for value in source_ids if value]
        if not ids:
            return 0
        marks = ",".join("?" for _ in ids)
        with self.conn:
            cur = self.conn.execute(
                f"UPDATE extraction_state SET state = 'extracted', last_error = '', "
                f"next_attempt_at = '' "
                f"WHERE source_id IN ({marks}) AND state != 'extracted'",
                ids,
            )
        return int(cur.rowcount or 0)

    def mark_extraction_failed(
        self,
        source_ids: list[str],
        error_type: str,
        *,
        max_attempts: int = EXTRACTION_MAX_ATTEMPTS,
        now: str = "",
    ) -> int:
        """Retry with bounded exponential backoff; park the row after max_attempts.

        The terminal ``dead`` state keeps the immutable Source and the last error
        type, so an operator can inspect or requeue it without content loss.
        """
        ids = [str(value) for value in source_ids if value]
        if not ids:
            return 0
        marks = ",".join("?" for _ in ids)
        limit = max(1, int(max_attempts))
        current = now or _now()
        changed = 0
        with self.conn:
            rows = self.conn.execute(
                f"SELECT source_id, attempts FROM extraction_state "
                f"WHERE source_id IN ({marks}) AND state != 'extracted'",
                ids,
            ).fetchall()
            for row in rows:
                attempts = int(row["attempts"]) + 1
                terminal = attempts >= limit
                cur = self.conn.execute(
                    "UPDATE extraction_state SET state = ?, attempts = ?, "
                    "next_attempt_at = ?, last_error = ? WHERE source_id = ?",
                    (
                        "dead" if terminal else "retrying",
                        attempts,
                        "" if terminal else _backoff_at(current, attempts),
                        str(error_type or "Unknown")[:200],
                        str(row["source_id"]),
                    ),
                )
                changed += int(cur.rowcount or 0)
        return changed

    def ready_extraction_ids(self, now: str = "") -> set[str]:
        """Return queued source ids whose retry backoff has already elapsed."""
        current = now or _now()
        rows = self.conn.execute(
            "SELECT source_id FROM extraction_state "
            "WHERE state IN ('pending', 'retrying') "
            "AND (next_attempt_at = '' OR next_attempt_at <= ?)",
            (current,),
        ).fetchall()
        return {str(row["source_id"]) for row in rows}

    def capacity_usage(self, now: str = "") -> dict[str, int | float]:
        """Return non-sensitive usage counters for the pure CapacityGovernor."""
        source = self.conn.execute(
            "SELECT COUNT(*) AS rows, "
            "COALESCE(SUM(LENGTH(CAST(b.content AS BLOB))), 0) AS bytes "
            "FROM sources s JOIN blobs b ON b.hash = s.blob"
        ).fetchone()
        active = self.conn.execute(
            "SELECT COUNT(*) AS rows, "
            "COALESCE(SUM(LENGTH(CAST(b.content AS BLOB))), 0) AS bytes "
            "FROM nodes n JOIN blobs b ON b.hash = n.blob "
            "WHERE n.state = 'active'"
        ).fetchone()
        pending = self.conn.execute(
            "SELECT COUNT(*) AS rows, MIN(created_at) AS oldest "
            "FROM extraction_state WHERE state IN ('pending', 'retrying')"
        ).fetchone()
        counts = self.queue_counts()
        current = _parse_time(now) or datetime.datetime.now()
        oldest = _parse_time(str(pending["oldest"] or ""))
        pending_age = _age_seconds(oldest, current)
        expired = 0
        for row in self.conn.execute(
            "SELECT time FROM nodes WHERE state = 'active'"
        ).fetchall():
            span = _loads(row["time"])
            deadline = span.get("expires") or span.get("valid_to")
            parsed = _parse_time(str(deadline or ""))
            if parsed is not None and parsed.date() < current.date():
                expired += 1
        return {
            "source_rows": int(source["rows"] or 0),
            "source_bytes": int(source["bytes"] or 0),
            "pending_rows": int(pending["rows"] or 0),
            "pending_oldest_age_seconds": pending_age,
            "deferred_rows": int(counts.get("deferred", 0)),
            "dead_rows": int(counts.get("dead", 0)),
            "artifact_count": int(active["rows"] or 0),
            "artifact_bytes": int(active["bytes"] or 0),
            "expired_artifacts": expired,
        }

    def append_state_event(self, event: StateEvent) -> None:
        event.validate()
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO state_events(id, entity, revision_seen, op, delta, at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.entity_id,
                    event.revision_seen,
                    event.op,
                    _dump(event.delta),
                    event.at or _now(),
                ),
            )

    def ledger_last_hash(self) -> str:
        """返回日志链尾的 self_hash；空链返回空串。"""
        row = self.conn.execute(
            "SELECT self_hash FROM ledger ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return str(row["self_hash"]) if row is not None else ""

    def ledger_append(
        self, op: str, entity: str, before: str | None, after: str | None, reason: str
    ) -> None:
        """追加一条日志，哈希链在此闭合。"""
        at = _now()
        prev = self.ledger_last_hash()
        payload = chain_payload(at, op, entity, before, after, reason)
        with self.conn:
            self.conn.execute(
                "INSERT INTO ledger(at, op, entity, before_hash, after_hash, reason, "
                "prev_hash, self_hash) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    at,
                    op,
                    entity,
                    before,
                    after,
                    reason,
                    prev,
                    chain_hash(prev, payload),
                ),
            )

    def ledger_entries(self) -> list[sqlite3.Row]:
        """按 seq 升序导出日志原始行，供 store/ledger.py 重算校验。"""
        return self.conn.execute(
            "SELECT at, op, entity, before_hash, after_hash, reason, prev_hash, "
            "self_hash FROM ledger ORDER BY seq"
        ).fetchall()

    def inspect_record(self, node_id: str) -> dict:
        """向已认证管理员返回版本哈希与证据。

        Args:
            node_id: Artifact 标识。

        Returns:
            版本快照与不可变证据，包含原始文本。
        """
        versions = self.conn.execute(
            "SELECT v.revision, v.op, v.at, v.blob, v.header, b.content FROM artifact_versions v "
            "LEFT JOIN blobs b ON b.hash = v.blob WHERE v.entity = ? "
            "ORDER BY v.revision DESC",
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

    def close(self) -> None:
        """关闭连接。"""
        self.conn.close()

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
        h, now = art.header, _now()
        with self.conn:
            row = self.conn.execute(
                "SELECT revision FROM nodes WHERE id = ?", (h.id,)
            ).fetchone()
            current = int(row["revision"]) if row is not None else 0
            if current != int(expected_revision):
                raise VersionError(
                    f"revision conflict: expected {expected_revision}, current {current}"
                )
            prev = self.get(h.id) if current else None
            assert_next_revision(prev, art)
            content = _dump(art.payload)
            blob = hashlib.sha256(content.encode("utf-8")).hexdigest()
            level, parent = art.payload.get("level"), art.payload.get("parent")
            args = (
                h.id,
                h.family,
                level if isinstance(level, str) else None,
                parent if isinstance(parent, str) else None,
                blob,
                h.state,
                h.scope,
                _dump(h.strength),
                _dump(h.time),
                h.said_by,
                h.shareable,
                h.time.created or now,
                h.time.updated or now,
                int(h.revision),
                _dump(h.lineage),
                h.subject_id,
            )
            header = _dump(
                {
                    "state": h.state,
                    "scope": h.scope,
                    "strength": _dump(h.strength),
                    "time": _dump(h.time),
                    "said_by": h.said_by,
                    "revision": int(h.revision),
                    "lineage": _dump(h.lineage),
                    "subject_id": h.subject_id,
                }
            )
            self.conn.execute(
                "INSERT OR IGNORE INTO blobs(hash, content, at) VALUES(?, ?, ?)",
                (blob, content, now),
            )
            self.conn.execute(_UPSERT, args)
            self.conn.execute(
                "INSERT INTO versions(entity, revision, blob, header, at) VALUES(?, ?, ?, ?, ?)",
                (h.id, int(h.revision), blob, header, now),
            )
            self.conn.execute(
                "INSERT INTO artifact_versions(entity, revision, op, blob, header, at) "
                "VALUES(?, ?, ?, ?, ?, ?)",
                (h.id, int(h.revision), op, blob, header, now),
            )
            for source_id in source_ids:
                self.conn.execute(
                    "INSERT OR IGNORE INTO artifact_evidence(entity, revision, source) "
                    "VALUES(?, ?, ?)",
                    (h.id, int(h.revision), str(source_id)),
                )
            for event in state_events:
                event.validate()
                self.conn.execute(
                    "INSERT OR IGNORE INTO state_events(id, entity, revision_seen, op, delta, at) "
                    "VALUES(?, ?, ?, ?, ?, ?)",
                    (
                        event.id,
                        event.entity_id,
                        event.revision_seen,
                        event.op,
                        _dump(event.delta),
                        event.at or now,
                    ),
                )
            before = str(current) if current else None
            self._ledger_append_conn(op, h.id, before, str(h.revision), reason, now)

    def _ledger_append_conn(
        self,
        op: str,
        entity: str,
        before: str | None,
        after: str | None,
        reason: str,
        at: str | None = None,
    ) -> None:
        at = at or _now()
        row = self.conn.execute(
            "SELECT self_hash FROM ledger ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        prev = str(row["self_hash"]) if row is not None else ""
        payload = chain_payload(at, op, entity, before, after, reason)
        self.conn.execute(
            "INSERT INTO ledger(at, op, entity, before_hash, after_hash, reason, "
            "prev_hash, self_hash) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
            (at, op, entity, before, after, reason, prev, chain_hash(prev, payload)),
        )

    @staticmethod
    def _to_artifact(row: sqlite3.Row | None) -> Artifact | None:
        """把查询行还原成 Artifact；损坏行返回 None（fail-open）。"""
        if row is None or not row["blob_content"]:
            return None
        try:
            lineage = _pick(Lineage, _loads(row["lineage"]))
            for key in ("sources", "derived_from"):  # JSON 数组还原成契约里的 tuple
                lineage[key] = tuple(lineage.get(key) or ())
            header = Header(
                id=str(row["id"]),
                family=str(row["family"]),
                revision=int(row["revision"] or 1),
                state=str(row["state"]),
                scope=str(row["scope"]),
                lineage=Lineage(**lineage),
                strength=Strength(**_pick(Strength, _loads(row["strength"]))),
                time=TimeSpan(**_pick(TimeSpan, _loads(row["time"]))),
                said_by=str(row["said_by"]),
                shareable=str(row["shareable"]),
                subject_id=str(row["subject_id"] or ""),
            )
            payload = json.loads(row["blob_content"])
        except (TypeError, ValueError, KeyError):
            return None
        return Artifact(
            header=header, payload=payload if isinstance(payload, dict) else {}
        )
