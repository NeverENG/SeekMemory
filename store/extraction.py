"""Own evidence admission and extraction queue transitions over a shared connection.

通过共享连接管理证据接纳及抽取队列状态变化。
"""

from __future__ import annotations

import datetime
from typing import Any

try:
    from .sources import write_source_conn
    from .sqlite import SqliteRepository, load_json_object, now_iso, parse_time
except ImportError:
    from sources import write_source_conn
    from sqlite import SqliteRepository, load_json_object, now_iso, parse_time

try:
    from ..core.source import Source
except ImportError:
    from core.source import Source

EXTRACTION_MAX_ATTEMPTS = 5
_EXTRACTION_BACKOFF_BASE_SECONDS = 30
_EXTRACTION_BACKOFF_CAP_SECONDS = 3600


def _backoff_at(now: str, attempt: int) -> str:
    """Compute bounded exponential retry time without changing stored timestamps / 计算有上限的指数重试时间，不改变已存时间戳。"""
    base = parse_time(now) or datetime.datetime.now()
    delay = min(
        _EXTRACTION_BACKOFF_CAP_SECONDS,
        _EXTRACTION_BACKOFF_BASE_SECONDS * 2 ** max(0, attempt - 1),
    )
    return (base + datetime.timedelta(seconds=delay)).isoformat(timespec="seconds")


class ExtractionRepository(SqliteRepository):
    """Own rebuildable queue state and atomic Source admission / 管理可重建的队列状态及原始消息原子入队。"""

    def enqueue_extraction(
        self,
        source: Source,
        topic_id: str,
        created_at: str = "",
        *,
        deferred: bool = False,
    ) -> bool:
        """Append immutable evidence and its queue reference in one transaction / 在同一事务中追加不可变证据及队列引用。"""
        moment = source.at or created_at or now_iso()
        state = "deferred" if deferred else "pending"
        with self.conn:
            write_source_conn(self.conn, source, moment)
            cur = self.conn.execute(
                "INSERT OR IGNORE INTO extraction_state("
                "source_id, turn_id, session_id, topic_id, state, attempts, "
                "next_attempt_at, last_error, created_at) "
                "VALUES(?, ?, ?, ?, ?, 0, '', '', ?)",
                (source.id, source.turn_id, source.session_id, topic_id, state, moment),
            )
        return bool(cur.rowcount)

    def release_deferred(self, limit: int = 50) -> int:
        """Admit a bounded set of deferred rows in one transaction / 在一个事务中限量接纳延后处理行。"""
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

    def pending_extractions(self, now: str = "") -> list[dict[str, Any]]:
        """Read queued Source projections with optional retry-time filtering / 读取队列中的原始消息视图，可按重试时间筛选。"""
        rows = self.conn.execute(
            "SELECT e.source_id, e.turn_id, e.session_id, e.topic_id, e.state, "
            "e.attempts, e.next_attempt_at, e.last_error, e.created_at, "
            "s.role, s.at, s.flags, b.content AS text "
            "FROM extraction_state e "
            "JOIN sources s ON s.id = e.source_id "
            "JOIN blobs b ON b.hash = s.blob "
            "WHERE e.state IN ('pending', 'retrying') "
            "AND (? = '' OR e.next_attempt_at = '' OR e.next_attempt_at <= ?) "
            "ORDER BY e.created_at, e.source_id",
            (str(now or ""), str(now or "")),
        ).fetchall()
        out = []
        for row in rows:
            flags = load_json_object(row["flags"])
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
                    "reply_to": str(flags.get("reply_to") or ""),
                    "state": str(row["state"]),
                    "attempts": int(row["attempts"]),
                    "next_attempt_at": str(row["next_attempt_at"]),
                    "last_error": str(row["last_error"]),
                    "created_at": str(row["created_at"]),
                }
            )
        return out

    def queue_counts(self) -> dict[str, int]:
        """Count rows by extraction state / 按抽取状态统计行数。"""
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
        """Confirm only supplied IDs; keep immutable evidence and other input / 仅确认给定编号，保留不可变证据及其他输入。"""
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
        """Retain unfinished rows with bounded attempts and retry times / 保留未完成行并记录有上限的尝试次数和重试时间。"""
        ids = [str(value) for value in source_ids if value]
        if not ids:
            return 0
        marks = ",".join("?" for _ in ids)
        limit = max(1, int(max_attempts))
        current = now or now_iso()
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
        """Read queued IDs whose retry delay has elapsed / 读取已到重试时间的队列编号。"""
        current = now or now_iso()
        rows = self.conn.execute(
            "SELECT source_id FROM extraction_state "
            "WHERE state IN ('pending', 'retrying') "
            "AND (next_attempt_at = '' OR next_attempt_at <= ?)",
            (current,),
        ).fetchall()
        return {str(row["source_id"]) for row in rows}
