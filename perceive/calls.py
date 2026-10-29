"""Append bounded content-free recall diagnostics; file failures do not interrupt chat.

追加有数量上限且无正文的召回诊断，文件失败不中断聊天。
"""

from __future__ import annotations

import datetime
import json
import os

MAX_BYTES = 4 * 1024 * 1024


def log_call(path: str, umo: str, info: dict) -> None:
    """Append bounded structural recall counts without message bodies; contain failures / 追加有数量上限的结构化召回计数，不含消息正文，并隔离失败。"""
    try:
        if not path:
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > MAX_BYTES:
            os.replace(path, path + ".1")
        kind = str(umo or "").split(":")
        rec = {
            "t": datetime.datetime.now().isoformat(timespec="seconds"),
            "kind": kind[1] if len(kind) > 1 else "unknown",
            "mode": str(info.get("mode") or "strict"),
            "picked": int(info.get("picked") or 0),
            "pinned": int(info.get("pinned") or 0),
            "chars": int(info.get("chars") or 0),
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:  # noqa: BLE001 - Diagnostics cannot block replies / 诊断不能阻塞回复。
        pass
