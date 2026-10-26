"""SQLite connection, schema and migration owner."""

from __future__ import annotations

import dataclasses
import datetime
import json
import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("schema.sql")


def now_iso() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def dump_json(value: Any) -> str:
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def load_json_any(raw: Any, default: Any) -> Any:
    try:
        return json.loads(raw if raw not in (None, "") else dump_json(default))
    except (TypeError, ValueError):
        return default


def load_json_object(raw: Any) -> dict[str, Any]:
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def pick_dataclass_fields(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    names = {field.name for field in dataclasses.fields(cls)}
    return {key: value for key, value in data.items() if key in names}


def parse_time(value: str) -> datetime.datetime | None:
    try:
        return datetime.datetime.fromisoformat(str(value or "").strip())
    except (TypeError, ValueError):
        return None


def age_seconds(value: datetime.datetime | None, now: datetime.datetime) -> float:
    if value is None:
        return 0.0
    try:
        return max(0.0, now.timestamp() - value.timestamp())
    except (OSError, OverflowError, ValueError):
        return 0.0


class SqliteDatabase:
    """Own one SQLite connection and every schema migration."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;")
        self.conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        self._migrate()

    def _migrate(self) -> None:
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(nodes)")}
        state_cols = {
            row[1] for row in self.conn.execute("PRAGMA table_info(extraction_state)")
        }
        version_cols = {
            row[1] for row in self.conn.execute("PRAGMA table_info(versions)")
        }
        episode_cols = {
            row[1] for row in self.conn.execute("PRAGMA table_info(runtime_episodes)")
        }
        import_cols = {
            row[1] for row in self.conn.execute("PRAGMA table_info(history_import_tasks)")
        }
        preflight_cols = {
            row[1]
            for row in self.conn.execute("PRAGMA table_info(history_import_preflight)")
        }
        with self.conn:
            for name, definition in (
                ("subject_id", "TEXT NOT NULL DEFAULT ''"),
                ("revision", "INTEGER NOT NULL DEFAULT 1"),
                ("lineage", "TEXT NOT NULL DEFAULT '{}'"),
            ):
                if name not in cols:
                    self.conn.execute(
                        f"ALTER TABLE nodes ADD COLUMN {name} {definition}"
                    )
            if state_cols and "next_attempt_at" not in state_cols:
                self.conn.execute(
                    "ALTER TABLE extraction_state ADD COLUMN "
                    "next_attempt_at TEXT NOT NULL DEFAULT ''"
                )
            if version_cols:
                header = "header" if "header" in version_cols else "'{}'"
                self.conn.execute(
                    "INSERT OR IGNORE INTO artifact_versions("
                    "entity, revision, op, blob, header, at) "
                    "SELECT entity, revision, 'migrate', blob, "
                    f"{header}, at FROM versions"
                )
            if episode_cols and "run_id" not in episode_cols:
                self.conn.execute(
                    "ALTER TABLE runtime_episodes "
                    "ADD COLUMN run_id TEXT NOT NULL DEFAULT ''"
                )
            if import_cols and "selection_json" not in import_cols:
                self.conn.execute(
                    "ALTER TABLE history_import_tasks "
                    "ADD COLUMN selection_json TEXT NOT NULL DEFAULT '{}'"
                )
            for name, definition in (
                ("role", "TEXT NOT NULL DEFAULT ''"),
                ("reply_to", "TEXT NOT NULL DEFAULT ''"),
            ):
                if name not in preflight_cols:
                    self.conn.execute(
                        f"ALTER TABLE history_import_preflight ADD COLUMN {name} {definition}"
                    )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_nodes_subject ON nodes(subject_id)"
            )
            self.conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_episodes_run "
                "ON runtime_episodes(run_id) WHERE run_id <> ''"
            )
            self.conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_history_import_preflight_reply "
                "ON history_import_preflight(stage_key, reply_to) "
                "WHERE reply_to <> ''"
            )

    def close(self) -> None:
        self.conn.close()


class SqliteRepository:
    """Base for repositories sharing one SqliteDatabase."""

    def __init__(self, db: SqliteDatabase) -> None:
        self.db = db

    @property
    def conn(self):
        return self.db.conn
