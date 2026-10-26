"""Persistent task and task-to-Source projection for private history imports."""

from __future__ import annotations

import json
import re
import datetime as dt
import hashlib
from typing import Any

try:
    from .sources import source_flags, write_source_conn
    from .sqlite import SqliteRepository, dump_json, load_json_any, now_iso
except ImportError:
    from sources import source_flags, write_source_conn
    from sqlite import SqliteRepository, dump_json, load_json_any, now_iso

try:
    from ..core.source import SourceQueueEntry
except ImportError:
    from core.source import SourceQueueEntry

ACTIVE_IMPORT_STATES = ("queued", "running", "interrupted")
TERMINAL_IMPORT_STATES = ("completed", "partial", "failed", "cancelled", "abandoned")
_ERROR_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,79}$")


class SourceIdentityConflict(ValueError):
    """An imported external identity already names different immutable data."""


def _summary(row: Any) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "status": str(row["status"]),
        "format_id": str(row["format_id"]),
        "source_count": int(row["source_count"]),
        "duplicate_count": int(row["duplicate_count"]),
        "skipped_count": int(row["skipped_count"]),
        "pending_count": int(row["pending_count"]),
        "extracted_count": int(row["extracted_count"]),
        "failed_count": int(row["failed_count"]),
        "error_types": load_json_any(row["error_types"], []),
        "persona_status": str(row["persona_status"]),
        "can_retry": bool(
            str(row["stage_key"] or "")
            and str(row["status"]) in {"failed", "partial", "interrupted"}
        ),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
        "terminal_at": str(row["terminal_at"]),
    }


def _fingerprint(entry: SourceQueueEntry) -> str:
    source = entry.source
    value = [
        source.id,
        source.turn_id,
        source.session_id,
        source.speaker_id,
        source.role,
        source.text,
        source.at,
        source.reply_to,
        source.metadata,
    ]
    return hashlib.sha256(dump_json(value).encode("utf-8")).hexdigest()


def _matches_source(row: Any, source: Any, expected_flags: str) -> bool:
    return (
        str(row["umo"]) == source.session_id
        and str(row["at"]) == source.at
        and str(row["role"]) == source.role
        and str(row["blob"]) == source.content_hash
        and str(row["content"]) == source.text
        and str(row["flags"]) == expected_flags
    )


class HistoryImportRepository(SqliteRepository):
    """Own import lifecycle SQL and bounded Source/queue admission."""

    def create_task(
        self,
        task_id: str,
        stage_key: str,
        *,
        format_id: str = "chatlab",
        duplicate_count: int = 0,
        skipped_count: int = 0,
        selection: dict[str, str] | None = None,
        at: str = "",
    ) -> None:
        moment = at or now_iso()
        with self.conn:
            self.conn.execute(
                "INSERT INTO history_import_tasks(id, status, stage_key, format_id, "
                "duplicate_count, skipped_count, selection_json, created_at, updated_at) "
                "VALUES(?, 'queued', ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(task_id),
                    str(stage_key),
                    str(format_id),
                    max(0, int(duplicate_count)),
                    max(0, int(skipped_count)),
                    dump_json(selection or {}),
                    moment,
                    moment,
                ),
            )

    def recover_interrupted(self, at: str = "") -> int:
        moment = at or now_iso()
        marks = ",".join("?" for _ in ACTIVE_IMPORT_STATES[:2])
        with self.conn:
            cur = self.conn.execute(
                f"UPDATE history_import_tasks SET status = 'interrupted', updated_at = ? "
                f"WHERE status IN ({marks})",
                (moment, *ACTIVE_IMPORT_STATES[:2]),
            )
        return int(cur.rowcount or 0)

    def set_status(self, task_id: str, status: str, at: str = "") -> bool:
        if status not in {"queued", "running", "interrupted"}:
            raise ValueError("invalid nonterminal import status")
        moment = at or now_iso()
        with self.conn:
            cur = self.conn.execute(
                "UPDATE history_import_tasks SET status = ?, updated_at = ? "
                "WHERE id = ? AND status NOT IN ('completed','partial','failed','cancelled','abandoned')",
                (status, moment, str(task_id)),
            )
        return bool(cur.rowcount)

    def task(self, task_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM history_import_tasks WHERE id = ?", (str(task_id),)
        ).fetchone()
        return self._live_summary(row) if row is not None else None

    def task_stage(self, task_id: str) -> dict[str, str] | None:
        row = self.conn.execute(
            "SELECT id, stage_key, status, stage_expires_at, selection_json "
            "FROM history_import_tasks WHERE id = ?",
            (str(task_id),),
        ).fetchone()
        if row is None:
            return None
        return {key: str(row[key] or "") for key in row.keys()}

    def task_selection(self, task_id: str) -> dict[str, str] | None:
        row = self.conn.execute(
            "SELECT selection_json FROM history_import_tasks WHERE id = ?",
            (str(task_id),),
        ).fetchone()
        if row is None:
            return None
        data = load_json_any(row["selection_json"], {})
        if not isinstance(data, dict):
            return {}
        return {str(key): str(value) for key, value in data.items()}

    def release_stage(self, task_id: str) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE history_import_tasks SET stage_key = '', stage_expires_at = '', "
                "selection_json = '{}' "
                "WHERE id = ?",
                (str(task_id),),
            )
        return bool(cur.rowcount)

    def supersede_interrupted(self, old_task_id: str, new_task_id: str) -> int:
        """Move an interrupted task's live Source links to its explicit retry."""
        moment = now_iso()
        old_counts = self.counts(old_task_id)
        with self.conn:
            old = self.conn.execute(
                "SELECT status FROM history_import_tasks WHERE id = ?",
                (str(old_task_id),),
            ).fetchone()
            new = self.conn.execute(
                "SELECT status FROM history_import_tasks WHERE id = ?",
                (str(new_task_id),),
            ).fetchone()
            if old is None or str(old["status"]) != "interrupted":
                raise ValueError("retry_source_task_not_interrupted")
            if new is None or str(new["status"]) != "queued":
                raise ValueError("retry_destination_task_not_queued")
            self.conn.execute(
                "INSERT OR IGNORE INTO history_import_sources(task_id, source_id, topic_id, linked_at) "
                "SELECT ?, source_id, topic_id, ? FROM history_import_sources WHERE task_id = ?",
                (str(new_task_id), moment, str(old_task_id)),
            )
            moved = int(
                self.conn.execute(
                    "SELECT COUNT(*) FROM history_import_sources WHERE task_id = ?",
                    (str(new_task_id),),
                ).fetchone()[0]
            )
            self.conn.execute(
                "UPDATE history_import_tasks SET source_count = ?, updated_at = ? WHERE id = ?",
                (moved, moment, str(new_task_id)),
            )
            self.conn.execute(
                "UPDATE history_import_tasks SET status = 'abandoned', pending_count = ?, "
                "extracted_count = ?, failed_count = ?, updated_at = ?, terminal_at = ?, "
                "stage_key = '', stage_expires_at = '', selection_json = '{}' WHERE id = ?",
                (
                    old_counts["pending"],
                    old_counts["extracted"],
                    old_counts["failed"],
                    moment,
                    moment,
                    str(old_task_id),
                ),
            )
            self.conn.execute(
                "DELETE FROM history_import_sources WHERE task_id = ?",
                (str(old_task_id),),
            )
        return moved

    def list_tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        size = max(1, min(100, int(limit)))
        rows = self.conn.execute(
            "SELECT * FROM history_import_tasks ORDER BY created_at DESC, id DESC LIMIT ?",
            (size,),
        ).fetchall()
        return [self._live_summary(row) for row in rows]

    def _live_summary(self, row: Any) -> dict[str, Any]:
        result = _summary(row)
        if result["status"] in ACTIVE_IMPORT_STATES:
            counts = self.counts(result["id"])
            result.update(
                {
                    "pending_count": counts["pending"],
                    "extracted_count": counts["extracted"],
                    "failed_count": counts["failed"],
                }
            )
        return result

    def retained_stage_keys(self, *, now: str) -> set[str]:
        rows = self.conn.execute(
            "SELECT stage_key FROM history_import_tasks WHERE stage_key <> '' AND ("
            "status IN ('queued','running','interrupted') OR "
            "(stage_expires_at <> '' AND stage_expires_at > ?))",
            (str(now),),
        ).fetchall()
        return {str(row["stage_key"]) for row in rows}

    def clear_preflight(self, stage_key: str) -> int:
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM history_import_preflight WHERE stage_key = ?",
                (str(stage_key),),
            )
        return int(cur.rowcount or 0)

    def preflight_user_topics(
        self, stage_key: str, source_ids: list[str]
    ) -> dict[str, str]:
        """Read only the bounded user-topic references for a message batch."""
        ids = list(dict.fromkeys(str(value) for value in source_ids if value))
        if not ids:
            return {}
        rows = self.conn.execute(
            "SELECT source_id, topic_id FROM history_import_preflight "
            "WHERE stage_key = ? AND role = 'user' AND source_id IN ("
            + ",".join("?" for _ in ids)
            + ")",
            [str(stage_key), *ids],
        ).fetchall()
        return {str(row["source_id"]): str(row["topic_id"]) for row in rows}

    def prune_preflight(self, *, now: str, retention_hours: int = 1) -> int:
        with self.conn:
            cur = self.conn.execute(
                "DELETE FROM history_import_preflight WHERE created_at <= datetime(?, ?) ",
                (str(now), f"-{max(1, int(retention_hours))} hours"),
            )
        return int(cur.rowcount or 0)

    def validate_sources(
        self, stage_key: str, entries: list[SourceQueueEntry]
    ) -> dict[str, int]:
        """Check a bounded batch and remember only hashed immutable identities."""
        if not entries:
            return {"unique": 0, "duplicates": 0, "existing": 0}
        unique = duplicates = existing_count = 0
        moment = now_iso()
        with self.conn:
            for entry in entries:
                source = entry.source
                source.validate()
                fingerprint = _fingerprint(entry)
                old = self.conn.execute(
                    "SELECT fingerprint FROM history_import_preflight "
                    "WHERE stage_key = ? AND source_id = ?",
                    (str(stage_key), source.id),
                ).fetchone()
                if old is not None:
                    if str(old["fingerprint"]) != fingerprint:
                        raise SourceIdentityConflict("source_identity_conflict")
                    duplicates += 1
                    continue
                expected_flags = dump_json(source_flags(source))
                existing_source = self.conn.execute(
                    "SELECT s.umo, s.at, s.role, s.blob, s.flags, b.content "
                    "FROM sources s JOIN blobs b ON b.hash = s.blob WHERE s.id = ?",
                    (source.id,),
                ).fetchone()
                if existing_source is not None and not _matches_source(
                    existing_source, source, expected_flags
                ):
                    raise SourceIdentityConflict("source_identity_conflict")
                if existing_source is not None:
                    existing_count += 1
                self.conn.execute(
                    "INSERT INTO history_import_preflight("
                    "stage_key, source_id, fingerprint, topic_id, role, reply_to, created_at) "
                    "VALUES(?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(stage_key),
                        source.id,
                        fingerprint,
                        entry.topic_id,
                        source.role,
                        source.reply_to or "",
                        moment,
                    ),
                )
                if source.role == "user":
                    self.conn.execute(
                        "UPDATE history_import_preflight SET topic_id = ? "
                        "WHERE stage_key = ? AND role = 'assistant' AND reply_to = ?",
                        (entry.topic_id, str(stage_key), source.id),
                    )
                unique += 1
        return {"unique": unique, "duplicates": duplicates, "existing": existing_count}

    def admit_sources(
        self,
        task_id: str,
        entries: list[SourceQueueEntry],
        *,
        stage_key: str = "",
    ) -> int:
        """Atomically admit one bounded batch and link each Source to its task."""
        if not entries:
            return 0
        moment = now_iso()
        linked = 0
        with self.conn:
            task = self.conn.execute(
                "SELECT status FROM history_import_tasks WHERE id = ?", (str(task_id),)
            ).fetchone()
            if task is None or str(task["status"]) not in ACTIVE_IMPORT_STATES:
                raise ValueError("import task is not active")
            for entry in entries:
                source = entry.source
                source.validate()
                fingerprint = _fingerprint(entry)
                staged = self.conn.execute(
                    "SELECT fingerprint, topic_id FROM history_import_preflight "
                    "WHERE stage_key = ? AND source_id = ?",
                    (str(stage_key), source.id),
                ).fetchone()
                if staged is None or str(staged["fingerprint"]) != fingerprint:
                    raise ValueError("import_preflight_mismatch")
                topic_id = str(staged["topic_id"])
                existing = self.conn.execute(
                    "SELECT s.umo, s.at, s.role, s.blob, s.flags, b.content "
                    "FROM sources s JOIN blobs b ON b.hash = s.blob WHERE s.id = ?",
                    (source.id,),
                ).fetchone()
                expected_flags = dump_json(source_flags(source))
                if existing is not None:
                    if not _matches_source(existing, source, expected_flags):
                        raise SourceIdentityConflict("source_identity_conflict")
                else:
                    write_source_conn(self.conn, source, source.at)

                active_owner = self.conn.execute(
                    "SELECT 1 FROM history_import_sources hs "
                    "JOIN history_import_tasks ht ON ht.id = hs.task_id "
                    "WHERE hs.source_id = ? AND hs.task_id <> ? "
                    "AND ht.status IN ('queued','running','interrupted') LIMIT 1",
                    (source.id, str(task_id)),
                ).fetchone()
                if active_owner is not None:
                    raise ValueError("source_already_in_active_import")

                state = self.conn.execute(
                    "SELECT state FROM extraction_state WHERE source_id = ?",
                    (source.id,),
                ).fetchone()
                if state is None:
                    self.conn.execute(
                        "INSERT INTO extraction_state(source_id, turn_id, session_id, "
                        "topic_id, state, attempts, next_attempt_at, last_error, created_at) "
                        "VALUES(?, ?, ?, ?, 'pending', 0, '', '', ?)",
                        (source.id, source.turn_id, source.session_id, topic_id, moment),
                    )
                elif str(state["state"]) != "extracted":
                    self.conn.execute(
                        "UPDATE extraction_state SET turn_id = ?, session_id = ?, topic_id = ?, "
                        "state = 'pending', attempts = 0, next_attempt_at = '', last_error = '' "
                        "WHERE source_id = ?",
                        (source.turn_id, source.session_id, topic_id, source.id),
                    )
                cur = self.conn.execute(
                    "INSERT OR IGNORE INTO history_import_sources(task_id, source_id, topic_id, linked_at) "
                    "VALUES(?, ?, ?, ?)",
                    (str(task_id), source.id, topic_id, moment),
                )
                linked += int(cur.rowcount or 0)
            self.conn.execute(
                "UPDATE history_import_tasks SET source_count = ("
                "SELECT COUNT(*) FROM history_import_sources WHERE task_id = ?), updated_at = ? "
                "WHERE id = ?",
                (str(task_id), moment, str(task_id)),
            )
        return linked

    def topic_ids(
        self, task_id: str, *, after_topic_id: str = "", limit: int = 500
    ) -> list[str]:
        size = max(1, min(500, int(limit)))
        rows = self.conn.execute(
            "SELECT hs.topic_id FROM history_import_sources hs "
            "JOIN extraction_state e ON e.source_id = hs.source_id "
            "WHERE hs.task_id = ? AND hs.topic_id > ? "
            "AND e.state IN ('pending','retrying') "
            "GROUP BY hs.topic_id ORDER BY hs.topic_id LIMIT ?",
            (str(task_id), str(after_topic_id), size),
        ).fetchall()
        return [str(row[0]) for row in rows]

    def next_ready_topic(self, task_id: str, *, now: str) -> str:
        row = self.conn.execute(
            "SELECT hs.topic_id FROM extraction_state e "
            "JOIN history_import_sources hs ON hs.source_id = e.source_id "
            "WHERE hs.task_id = ? AND e.state = 'retrying' "
            "AND (e.next_attempt_at = '' OR e.next_attempt_at <= ?) "
            "ORDER BY e.next_attempt_at, e.created_at, hs.topic_id LIMIT 1",
            (str(task_id), str(now)),
        ).fetchone()
        return str(row["topic_id"]) if row is not None else ""

    def topic_sources(
        self,
        task_id: str,
        topic_id: str,
        *,
        limit: int = 121,
        now: str = "",
    ) -> list[dict[str, Any]]:
        size = max(1, min(121, int(limit)))
        rows = self.conn.execute(
            "SELECT e.source_id, e.turn_id, e.session_id, e.topic_id, e.state, "
            "e.attempts, e.next_attempt_at, e.last_error, s.role, s.at, s.flags, b.content AS text "
            "FROM history_import_sources hs "
            "JOIN extraction_state e ON e.source_id = hs.source_id "
            "JOIN sources s ON s.id = hs.source_id "
            "JOIN blobs b ON b.hash = s.blob "
            "WHERE hs.task_id = ? AND hs.topic_id = ? AND e.state IN ('pending','retrying') "
            "AND (? = '' OR e.next_attempt_at = '' OR e.next_attempt_at <= ?) "
            "ORDER BY s.at, hs.source_id LIMIT ?",
            (str(task_id), str(topic_id), str(now), str(now), size),
        ).fetchall()
        return [
            {
                "source_id": str(row["source_id"]),
                "turn_id": str(row["turn_id"]),
                "session_id": str(row["session_id"]),
                "topic_id": str(row["topic_id"]),
                "state": str(row["state"]),
                "attempts": int(row["attempts"]),
                "next_attempt_at": str(row["next_attempt_at"]),
                "last_error": str(row["last_error"]),
                "speaker_id": str(load_json_any(row["flags"], {}).get("speaker_id") or ""),
                "role": str(row["role"]),
                "text": str(row["text"]),
                "at": str(row["at"]),
                "reply_to": str(load_json_any(row["flags"], {}).get("reply_to") or ""),
            }
            for row in rows
        ]

    def counts(self, task_id: str) -> dict[str, int]:
        result = {"pending": 0, "extracted": 0, "failed": 0}
        rows = self.conn.execute(
            "SELECT e.state, COUNT(*) AS amount FROM history_import_sources hs "
            "JOIN extraction_state e ON e.source_id = hs.source_id "
            "WHERE hs.task_id = ? GROUP BY e.state",
            (str(task_id),),
        ).fetchall()
        for row in rows:
            state, amount = str(row["state"]), int(row["amount"])
            if state in {"pending", "retrying", "deferred"}:
                result["pending"] += amount
            elif state == "extracted":
                result["extracted"] += amount
            elif state == "dead":
                result["failed"] += amount
        return result

    def next_attempt_at(self, task_id: str) -> str:
        row = self.conn.execute(
            "SELECT MIN(e.next_attempt_at) AS next_at FROM history_import_sources hs "
            "JOIN extraction_state e ON e.source_id = hs.source_id "
            "WHERE hs.task_id = ? AND e.state = 'retrying' AND e.next_attempt_at <> ''",
            (str(task_id),),
        ).fetchone()
        return str(row["next_at"] or "") if row is not None else ""

    def finish_task(
        self,
        task_id: str,
        status: str,
        *,
        persona_status: str,
        error_types: list[str] | None = None,
        retain_stage: bool = False,
        at: str = "",
    ) -> dict[str, int]:
        if status not in TERMINAL_IMPORT_STATES:
            raise ValueError("invalid terminal import status")
        moment = at or now_iso()
        expiry = ""
        if retain_stage:
            try:
                expiry = (
                    dt.datetime.fromisoformat(moment) + dt.timedelta(hours=24)
                ).isoformat(timespec="seconds")
            except ValueError:
                expiry = (dt.datetime.now() + dt.timedelta(hours=24)).isoformat(
                    timespec="seconds"
                )
        if status in {"failed", "cancelled", "abandoned"}:
            with self.conn:
                self.conn.execute(
                    "UPDATE extraction_state SET state = 'dead', attempts = MAX(attempts, 1), "
                    "next_attempt_at = '', last_error = ? WHERE source_id IN ("
                    "SELECT source_id FROM history_import_sources WHERE task_id = ?) "
                    "AND state IN ('pending','retrying','deferred')",
                    ("ImportCancelled" if status == "cancelled" else "ImportFailed", str(task_id)),
                )
        counts = self.counts(task_id)
        if status == "completed" and counts["pending"]:
            raise ValueError("cannot_complete_import_with_pending_sources")
        task_row = self.conn.execute(
            "SELECT stage_key FROM history_import_tasks WHERE id = ?", (str(task_id),)
        ).fetchone()
        stage_key = str(task_row["stage_key"] or "") if task_row is not None else ""
        errors = []
        for value in error_types or []:
            name = str(value or "")
            if _ERROR_NAME.fullmatch(name) and name not in errors:
                errors.append(name)
            if len(errors) >= 20:
                break
        with self.conn:
            self.conn.execute(
                "UPDATE history_import_tasks SET status = ?, pending_count = ?, "
                "extracted_count = ?, failed_count = ?, error_types = ?, persona_status = ?, "
                "updated_at = ?, terminal_at = ?, stage_key = CASE WHEN ? THEN stage_key ELSE '' END, "
                "stage_expires_at = ?, selection_json = CASE WHEN ? THEN selection_json ELSE '{}' END "
                "WHERE id = ?",
                (
                    status,
                    counts["pending"],
                    counts["extracted"],
                    counts["failed"],
                    dump_json(errors),
                    str(persona_status)[:40],
                    moment,
                    moment,
                    1 if retain_stage else 0,
                    expiry,
                    1 if retain_stage else 0,
                    str(task_id),
                ),
            )
            self.conn.execute(
                "DELETE FROM history_import_sources WHERE task_id = ?", (str(task_id),)
            )
            if stage_key and not retain_stage:
                self.conn.execute(
                    "DELETE FROM history_import_preflight WHERE stage_key = ?",
                    (stage_key,),
                )
        return counts

    def abandon_task(self, task_id: str, at: str = "") -> bool:
        moment = at or now_iso()
        with self.conn:
            cur = self.conn.execute(
                "UPDATE history_import_tasks SET status = 'abandoned', stage_key = '', "
                "stage_expires_at = '', selection_json = '{}', updated_at = ?, "
                "terminal_at = ? WHERE id = ? "
                "AND status IN ('queued','interrupted','failed','partial')",
                (moment, moment, str(task_id)),
            )
            if cur.rowcount:
                self.conn.execute(
                    "UPDATE extraction_state SET state = 'dead', attempts = MAX(attempts, 1), "
                    "next_attempt_at = '', last_error = 'ImportAbandoned' "
                    "WHERE source_id IN (SELECT source_id FROM history_import_sources WHERE task_id = ?) "
                    "AND state IN ('pending','retrying','deferred')",
                    (str(task_id),),
                )
                self.conn.execute(
                    "DELETE FROM history_import_sources WHERE task_id = ?", (str(task_id),)
                )
        return bool(cur.rowcount)

    def prune(self, *, now: str, retention_days: int = 30) -> int:
        cutoff = f"-{max(1, int(retention_days))} days"
        with self.conn:
            self.conn.execute(
                "DELETE FROM history_import_preflight WHERE created_at <= datetime(?, '-1 hour')",
                (now,),
            )
            expired_stages = self.conn.execute(
                "SELECT stage_key FROM history_import_tasks WHERE stage_key <> '' "
                "AND stage_expires_at <> '' AND stage_expires_at <= ?",
                (now,),
            ).fetchall()
            for row in expired_stages:
                self.conn.execute(
                    "DELETE FROM history_import_preflight WHERE stage_key = ?",
                    (str(row["stage_key"]),),
                )
            self.conn.execute(
                "UPDATE history_import_tasks SET stage_key = '', stage_expires_at = '', "
                "selection_json = '{}' "
                "WHERE stage_expires_at <> '' AND stage_expires_at <= ?",
                (now,),
            )
            cur = self.conn.execute(
                "DELETE FROM history_import_tasks WHERE status IN "
                "('completed','partial','failed','cancelled','abandoned') "
                "AND terminal_at <> '' AND terminal_at <= datetime(?, ?)",
                (now, cutoff),
            )
        return int(cur.rowcount or 0)
