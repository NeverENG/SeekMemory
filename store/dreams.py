"""Persist daily cycle state using a borrowed connection; do not run extraction or maintenance.

使用借用连接保存每日整理状态，不执行抽取或维护。
"""

from __future__ import annotations

from typing import Any

try:
    from .sqlite import SqliteRepository, dump_json, load_json_any, now_iso
except ImportError:
    from sqlite import SqliteRepository, dump_json, load_json_any, now_iso


class DreamRepository(SqliteRepository):
    """Own daily run state, distinct from memory evidence or business version ledger / 管理每日运行状态，与记忆证据及业务版本账本分开。"""

    def get(self, dream_date: str) -> dict[str, Any] | None:
        """Read one daily run or None / 读取一个每日运行，不存在时返回空。"""
        row = self.conn.execute(
            "SELECT * FROM dream_runs WHERE dream_date = ?", (str(dream_date),)
        ).fetchone()
        if row is None:
            return None
        return {
            "date": str(row["dream_date"]),
            "status": str(row["status"]),
            "started_at": str(row["started_at"] or ""),
            "finished_at": str(row["finished_at"] or ""),
            "batches": int(row["batches"] or 0),
            "written": int(row["written"] or 0),
            "errors": load_json_any(row["errors"], []),
            "summary": load_json_any(row["summary"], {}),
        }

    def begin(self, dream_date: str, now: str = "") -> bool:
        """Start or resume a daily run; completed dates return False / 开始或恢复每日运行，已完成日期返回否。"""
        existing = self.get(dream_date)
        if existing is not None and existing["status"] == "done":
            return False
        stamp = now or now_iso()
        with self.conn:
            self.conn.execute(
                "INSERT INTO dream_runs(dream_date, status, started_at) "
                "VALUES(?, 'running', ?) "
                "ON CONFLICT(dream_date) DO UPDATE SET "
                "status = 'running', started_at = excluded.started_at",
                (str(dream_date), stamp),
            )
        return True

    def finish(
        self,
        dream_date: str,
        *,
        status: str = "done",
        batches: int = 0,
        written: int = 0,
        errors: list[str] | None = None,
        summary: dict[str, Any] | None = None,
        now: str = "",
    ) -> None:
        """Update an existing daily run with completed counts and outcome; failures raise / 以已完成数量及结果更新已有每日运行，失败抛错。"""
        with self.conn:
            self.conn.execute(
                "UPDATE dream_runs SET status = ?, finished_at = ?, batches = ?, "
                "written = ?, errors = ?, summary = ? WHERE dream_date = ?",
                (
                    str(status),
                    now or now_iso(),
                    int(batches),
                    int(written),
                    dump_json(list(errors or [])),
                    dump_json(dict(summary or {})),
                    str(dream_date),
                ),
            )

    def recent(self, limit: int = 7) -> list[dict[str, Any]]:
        """Read a bounded set of recent daily runs / 限量读取近期每日运行。"""
        rows = self.conn.execute(
            "SELECT dream_date FROM dream_runs ORDER BY dream_date DESC LIMIT ?",
            (max(1, int(limit)),),
        ).fetchall()
        return [item for item in (self.get(str(row["dream_date"])) for row in rows) if item]
