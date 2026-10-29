"""Persist mutable scheduler state through a borrowed connection, independently of memory versions.

通过借用连接保存可变调度状态，与记忆版本分开。
"""

from __future__ import annotations

import json
from typing import Any

try:
    from .sqlite import SqliteRepository, dump_json, now_iso
except ImportError:
    from sqlite import SqliteRepository, dump_json, now_iso


class RuntimeStateRepository(SqliteRepository):
    """Own mutable scheduler state separately from versioned memory / 管理可变调度状态，与版本化记忆分开。"""

    def get(self, session_id: str) -> dict[str, Any]:
        """Read session state; absent or malformed legacy payload returns an empty object / 读取会话状态，不存在或旧内容格式错误时返回空对象。"""
        row = self.conn.execute(
            "SELECT payload FROM runtime_state WHERE session_id = ?",
            (str(session_id or ""),),
        ).fetchone()
        if row is None:
            return {}
        try:
            data = json.loads(row["payload"])
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def put(
        self,
        session_id: str,
        payload: dict[str, Any],
        updated_at: str = "",
    ) -> None:
        """Persist one session state in its own transaction / 在独立事务中保存一个会话状态。"""
        stamp = updated_at or now_iso()
        with self.conn:
            self.conn.execute(
                "INSERT INTO runtime_state(session_id, payload, updated_at) "
                "VALUES(?, ?, ?) ON CONFLICT(session_id) DO UPDATE SET "
                "payload=excluded.payload, updated_at=excluded.updated_at",
                (str(session_id or ""), dump_json(payload), stamp),
            )

    def sessions(self, limit: int = 1000) -> list[str]:
        """Read a bounded set of recently updated state session IDs / 限量读取近期更新的状态会话编号。"""
        rows = self.conn.execute(
            "SELECT session_id FROM runtime_state ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(10000, int(limit))),),
        ).fetchall()
        return [str(row["session_id"]) for row in rows]
