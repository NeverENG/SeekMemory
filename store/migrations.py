"""Apply existing compatible migrations in their established transaction order.

按既有事务顺序执行现有兼容迁移，不定义新的格式或时间转换；连接由调用方拥有。
"""
from __future__ import annotations

import sqlite3


def migrate(conn: sqlite3.Connection) -> None:
    """Inspect old columns, then execute the existing migration sequence / 检查旧字段，再执行既有迁移顺序。"""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(nodes)")}
    state_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(extraction_state)")
    }
    version_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(versions)")
    }
    episode_cols = {
        row[1] for row in conn.execute("PRAGMA table_info(runtime_episodes)")
    }
    with conn:
        _node_columns(conn, cols)
        _extraction_columns(conn, state_cols)
        _legacy_versions(conn, version_cols)
        _episode_columns(conn, episode_cols)
        _indexes(conn)


def _node_columns(conn: sqlite3.Connection, cols: set[str]) -> None:
    """Apply existing node-column additions / 执行既有记忆节点字段补充。"""
    for name, definition in (
        ("subject_id", "TEXT NOT NULL DEFAULT ''"),
        ("revision", "INTEGER NOT NULL DEFAULT 1"),
        ("lineage", "TEXT NOT NULL DEFAULT '{}'"),
    ):
        if name not in cols:
            conn.execute(
                f"ALTER TABLE nodes ADD COLUMN {name} {definition}"
            )


def _extraction_columns(conn: sqlite3.Connection, state_cols: set[str]) -> None:
    """Apply the existing queue retry column addition / 执行既有队列重试字段补充。"""
    if state_cols and "next_attempt_at" not in state_cols:
        conn.execute(
            "ALTER TABLE extraction_state ADD COLUMN "
            "next_attempt_at TEXT NOT NULL DEFAULT ''"
        )


def _legacy_versions(conn: sqlite3.Connection, version_cols: set[str]) -> None:
    """Copy legacy versions using the existing idempotent migration / 按既有幂等迁移复制旧版本。"""
    if version_cols:
        header = "header" if "header" in version_cols else "'{}'"
        conn.execute(
            "INSERT OR IGNORE INTO artifact_versions("
            "entity, revision, op, blob, header, at) "
            "SELECT entity, revision, 'migrate', blob, "
            f"{header}, at FROM versions"
        )


def _episode_columns(conn: sqlite3.Connection, episode_cols: set[str]) -> None:
    """Apply existing runtime episode and action columns / 执行既有运行记录及动作字段补充。"""
    if episode_cols and "run_id" not in episode_cols:
        conn.execute(
            "ALTER TABLE runtime_episodes "
            "ADD COLUMN run_id TEXT NOT NULL DEFAULT ''"
        )
    for name, definition in (
        ("action_id", "TEXT"),
        ("action_kind", "TEXT NOT NULL DEFAULT ''"),
        ("action_status", "TEXT NOT NULL DEFAULT ''"),
        ("attempt", "INTEGER NOT NULL DEFAULT 1"),
    ):
        if episode_cols and name not in episode_cols:
            conn.execute(
                f"ALTER TABLE runtime_episodes ADD COLUMN {name} {definition}"
            )


def _indexes(conn: sqlite3.Connection) -> None:
    """Apply the existing node/action indexes and trigger in order / 按顺序执行既有节点及动作索引和触发器。"""
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_nodes_subject ON nodes(subject_id)"
    )
    # Action events share run links; ordinary episodes retain one row per run.
    # 动作事件共享运行关联，普通运行记录仍保持每次运行一行。
    run_index = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'index' "
        "AND name = 'idx_runtime_episodes_run'"
    ).fetchone()
    if (
        run_index is not None
        and "action_id is null" not in str(run_index[0]).lower()
    ):
        conn.execute("DROP INDEX idx_runtime_episodes_run")
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_episodes_run "
        "ON runtime_episodes(run_id) "
        "WHERE run_id <> '' AND action_id IS NULL"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_runtime_episodes_action "
        "ON runtime_episodes(action_id, attempt) WHERE action_id IS NOT NULL"
    )
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_runtime_episodes_action_terminal "
        "ON runtime_episodes(action_id) "
        "WHERE action_id IS NOT NULL AND action_status IN "
        "('succeeded', 'failed', 'cancelled')"
    )
    conn.execute(
        "CREATE TRIGGER IF NOT EXISTS trg_runtime_action_no_attempt_after_terminal "
        "BEFORE INSERT ON runtime_episodes "
        "WHEN NEW.action_id IS NOT NULL "
        "AND NEW.action_status = 'attempted' "
        "AND EXISTS (SELECT 1 FROM runtime_episodes "
        "WHERE action_id = NEW.action_id AND action_status IN "
        "('succeeded', 'failed', 'cancelled')) "
        "BEGIN SELECT RAISE(IGNORE); END"
    )
