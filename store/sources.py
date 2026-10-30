"""Append immutable Source and read its projections; connection lifetime belongs to Store.

追加不可变原始消息并读取其视图，连接生命周期属于 Store。
"""

from __future__ import annotations

import sqlite3
from typing import Any

try:
    from .sqlite import SqliteRepository, dump_json, load_json_object, now_iso
except ImportError:
    from sqlite import SqliteRepository, dump_json, load_json_object, now_iso

try:
    from ..core.domain.memory.source import Source
except ImportError:
    from core.domain.memory.source import Source


def source_flags(source: Source) -> dict[str, Any]:
    """Prepare the existing Source metadata fields / 准备既有的原始消息元数据字段。"""
    return {
        "turn_id": source.turn_id,
        "speaker_id": source.speaker_id,
        "reply_to": source.reply_to,
        "metadata": source.metadata,
    }


def write_source_conn(
    conn: sqlite3.Connection,
    source: Source,
    at: str = "",
) -> int:
    """Insert one immutable Source inside the caller-owned transaction / 在调用方事务中插入一条不可变原始消息。"""
    source.validate()
    moment = source.at or at or now_iso()
    content_hash = source.content_hash
    conn.execute(
        "INSERT OR IGNORE INTO blobs(hash, content, at) VALUES(?, ?, ?)",
        (content_hash, source.text, moment),
    )
    cur = conn.execute(
        "INSERT OR IGNORE INTO sources(id, umo, at, role, blob, flags) "
        "VALUES(?, ?, ?, ?, ?, ?)",
        (
            source.id,
            source.session_id,
            moment,
            source.role,
            content_hash,
            dump_json(source_flags(source)),
        ),
    )
    return int(cur.rowcount or 0)


class SourceRepository(SqliteRepository):
    """Own append-only Source rows and immutable evidence reads / 管理仅追加的原始消息及不可变证据读取。"""

    def append_sources(self, sources: list[Source]) -> int:
        """Append evidence atomically and return newly inserted rows / 原子追加证据并返回新增行数。"""
        written = 0
        with self.conn:
            for source in sources:
                written += write_source_conn(self.conn, source)
        return written

    @staticmethod
    def _source_from_row(row: sqlite3.Row) -> Source:
        flags = load_json_object(row["flags"])
        metadata = flags.get("metadata")
        return Source(
            str(row["id"]),
            str(flags.get("turn_id") or ""),
            str(row["umo"]),
            str(flags.get("speaker_id") or ""),
            str(row["role"]),
            str(row["text"] or ""),
            str(row["at"] or ""),
            str(flags.get("reply_to") or "") or None,
            metadata if isinstance(metadata, dict) else {},
        )

    def recent_sources(self, *, since: str, limit: int) -> list[Source]:
        """Read globally ordered evidence within time and count limits / 在时间及数量限制内按全局顺序读取证据。"""
        if int(limit) <= 0:
            return []
        rows = self.conn.execute(
            "SELECT s.id, s.umo, s.at, s.role, s.flags, b.content AS text "
            "FROM sources s JOIN blobs b ON b.hash = s.blob "
            "WHERE s.at >= ? ORDER BY s.at DESC, s.id DESC LIMIT ?",
            (str(since or ""), int(limit)),
        ).fetchall()
        return [self._source_from_row(row) for row in rows]

    def source_umo(self, source_id: str) -> str:
        """Read a Sources originating session or an empty string / 读取原始消息的来源会话，不存在时返回空字符串。"""
        row = self.conn.execute(
            "SELECT umo FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        return str(row["umo"]) if row is not None else ""

    def source_umos(self, source_ids: list[str]) -> dict[str, str]:
        """Read originating sessions for supplied Source IDs / 读取给定原始消息编号的来源会话。"""
        ids = [str(value) for value in source_ids if value]
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            f"SELECT id, umo FROM sources WHERE id IN ({marks})", ids
        ).fetchall()
        return {str(row["id"]): str(row["umo"]) for row in rows}

    def sources_by_ids(self, source_ids: list[str]) -> dict[str, Source]:
        """Read immutable Source rows by ID / 按编号读取不可变原始消息。"""
        ids: list[str] = []
        for value in source_ids:
            text = str(value or "").strip()
            if text and text not in ids:
                ids.append(text)
        if not ids:
            return {}
        marks = ",".join("?" for _ in ids)
        rows = self.conn.execute(
            "SELECT s.id, s.umo, s.at, s.role, s.flags, b.content AS text "
            "FROM sources s JOIN blobs b ON b.hash = s.blob "
            f"WHERE s.id IN ({marks})",
            ids,
        ).fetchall()
        return {
            str(row["id"]): self._source_from_row(row)
            for row in rows
        }

    def latest_user_source(self, session_id: str) -> dict[str, Any] | None:
        """Read the latest user evidence in one session / 读取一个会话中的最新用户原始消息。"""
        row = self.conn.execute(
            "SELECT s.id, s.umo, s.at, s.role, b.content AS text "
            "FROM sources s JOIN blobs b ON b.hash = s.blob "
            "WHERE s.umo = ? AND s.role = 'user' "
            "ORDER BY s.at DESC, s.id DESC LIMIT 1",
            (str(session_id or ""),),
        ).fetchone()
        return dict(row) if row is not None else None
