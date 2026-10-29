"""Append content-free runtime audit and bounded retention over a borrowed connection.

通过借用连接追加无正文运行审计并限制保留数量。
"""

from __future__ import annotations

import datetime
import hashlib
import json
import math
import re
import time
from typing import Any

try:
    from .sqlite import SqliteRepository, now_iso
except ImportError:
    from sqlite import SqliteRepository, now_iso


_SAFE_ACTION_REASON = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,63}$")


def _safe_action_reason(value: Any) -> str:
    """Keep stable reason codes and discard free-form content / 保留稳定原因码并丢弃自由文本内容。"""
    reason = str(value or "").strip()
    if not reason:
        return ""
    return reason if _SAFE_ACTION_REASON.fullmatch(reason) else "error"


class RuntimeEpisodeRepository(SqliteRepository):
    """Own content-free run/action audit and its bounded cleanup / 管理无正文的运行及动作审计，并限制保留数量。"""

    def append(self, episode: dict[str, Any]) -> str:
        """Append one run episode with existing duplicate suppression; failures raise / 按既有去重规则追加一条运行记录，失败抛错。"""
        episode_id = str(episode.get("id") or f"ep_{time.time_ns()}")
        tool_calls = json.dumps(
            list(episode.get("tool_calls") or ()), ensure_ascii=False
        )
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO runtime_episodes("
                "id, at, session_id, decision, reason, action, delivered, "
                "response_chars, tool_calls, outcome, error, user_source_id, "
                "assistant_source_id, run_id) "
                "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    episode_id,
                    str(episode.get("at") or now_iso()),
                    str(episode.get("session_id") or ""),
                    str(episode.get("decision") or ""),
                    str(episode.get("reason") or ""),
                    str(episode.get("action") or ""),
                    int(bool(episode.get("delivered"))),
                    int(episode.get("response_chars") or 0),
                    tool_calls,
                    str(episode.get("outcome") or ""),
                    str(episode.get("error") or ""),
                    str(episode.get("user_source_id") or ""),
                    str(episode.get("assistant_source_id") or ""),
                    str(episode.get("run_id") or ""),
                ),
            )
        return episode_id

    def append_action(self, action: dict[str, Any]) -> bool:
        """Append an action attempt or first terminal status with stable identity; errors raise / 按稳定编号追加动作尝试或首次终态，错误时抛出。"""
        action_id = str(action.get("action_id") or "").strip()
        kind = str(action.get("action_kind") or "").strip()
        status = str(action.get("action_status") or "").strip()
        attempt = max(1, int(action.get("attempt") or 1))
        if not action_id:
            raise ValueError("action_id is required")
        if kind not in {"send_text", "tool_call", "host_action"}:
            raise ValueError("invalid action_kind")
        if status not in {"attempted", "succeeded", "failed", "cancelled"}:
            raise ValueError("invalid action_status")

        raw_at = float(action.get("at") or 0.0)
        if not math.isfinite(raw_at) or raw_at < 0.0:
            raise ValueError("action at must be finite and non-negative")
        at = datetime.datetime.fromtimestamp(
            raw_at, tz=datetime.timezone.utc
        ).isoformat(timespec="seconds")
        event_suffix = f"attempted:{attempt}" if status == "attempted" else "terminal"
        identity = hashlib.sha256(
            f"{action_id}\0{event_suffix}".encode("utf-8")
        ).hexdigest()
        terminal = status in {"succeeded", "failed", "cancelled"}
        with self.conn:
            if terminal:
                attempted = self.conn.execute(
                    "SELECT 1 FROM runtime_episodes WHERE action_id = ? "
                    "AND action_status = 'attempted' LIMIT 1",
                    (action_id,),
                ).fetchone()
                if attempted is None:
                    raise ValueError("terminal action requires a persisted attempt")
            cursor = self.conn.execute(
                "INSERT OR IGNORE INTO runtime_episodes("
                "id, at, session_id, decision, reason, action, delivered, "
                "response_chars, tool_calls, outcome, error, user_source_id, "
                "assistant_source_id, run_id, action_id, action_kind, "
                "action_status, attempt) "
                "VALUES(?, ?, ?, 'action', ?, ?, ?, 0, '[]', ?, '', '', '', ?, ?, ?, ?, ?)",
                (
                    f"act_{identity}",
                    at,
                    str(action.get("session_id") or ""),
                    _safe_action_reason(action.get("reason")),
                    kind,
                    int(status == "succeeded" and kind == "send_text"),
                    status,
                    str(action.get("run_id") or ""),
                    action_id,
                    kind,
                    status,
                    attempt,
                ),
            )
        return bool(cursor.rowcount)

    def list_actions(
        self, session_id: str = "", limit: int = 100
    ) -> list[dict[str, Any]]:
        """Read bounded action audit, optionally within one session / 限量读取动作审计，可限定一个会话。"""
        size = max(1, min(1000, int(limit)))
        if session_id:
            rows = self.conn.execute(
                "SELECT * FROM runtime_episodes WHERE action_id IS NOT NULL "
                "AND session_id = ? ORDER BY at DESC, rowid DESC LIMIT ?",
                (str(session_id), size),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM runtime_episodes WHERE action_id IS NOT NULL "
                "ORDER BY at DESC, rowid DESC LIMIT ?",
                (size,),
            ).fetchall()
        return [dict(row) for row in rows]

    def list(self, session_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        """Read bounded ordinary run episodes, excluding action transitions / 限量读取普通运行记录，排除动作状态变化。"""
        size = max(1, min(1000, int(limit)))
        if session_id:
            rows = self.conn.execute(
                "SELECT * FROM runtime_episodes WHERE action_id IS NULL "
                "AND session_id = ? ORDER BY at DESC, rowid DESC LIMIT ?",
                (str(session_id), size),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM runtime_episodes WHERE action_id IS NULL "
                "ORDER BY at DESC, rowid DESC LIMIT ?",
                (size,),
            ).fetchall()
        return [dict(row) for row in rows]

    def prune(self, retention_days: int = 30, max_rows: int = 5000) -> int:
        """Delete audit rows outside the existing age/count limits in one transaction / 在一个事务中删除超出既有时间和数量限制的审计行。"""
        days = max(0, int(retention_days))
        limit = max(1, int(max_rows))
        deleted = 0
        with self.conn:
            if days:
                cutoff = (
                    datetime.datetime.now() - datetime.timedelta(days=days)
                ).isoformat(timespec="seconds")
                cur = self.conn.execute(
                    "DELETE FROM runtime_episodes WHERE at < ?", (cutoff,)
                )
                deleted += int(cur.rowcount or 0)
            cur = self.conn.execute(
                "DELETE FROM runtime_episodes WHERE id IN ("
                "SELECT id FROM runtime_episodes ORDER BY at DESC, id DESC "
                "LIMIT -1 OFFSET ?)",
                (limit,),
            )
            deleted += int(cur.rowcount or 0)
        return deleted
