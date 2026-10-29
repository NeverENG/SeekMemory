"""Existing query configuration and recent-memory fallback rules; no writes.

既有查询配置及近期记忆回退规则，不执行写入；候选由调用方提供。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

Conf = Callable[[str, Any], Any]

def _conf_bool(conf: Conf, key: str, default: bool) -> bool:
    """Read existing boolean or string configuration values / 读取既有布尔或字符串配置值。"""
    value = conf(key, default)
    if isinstance(value, str):
        return value.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(value)


def subject_of(speaker: str, owner_umo: str) -> str:
    """Resolve current speaker identity for impression ranking / 确定当前说话人身份以排序印象。"""
    owner_id = str(owner_umo or "").split(":")[-1] if owner_umo else ""
    talker = str(speaker or "")
    if not talker:
        return "owner"
    return "owner" if owner_id and talker == owner_id else talker


def recent_context(pool: list, subject: str, *, profile: bool = False,
                   limit: int = 2) -> list:
    """Rank recent global memories; subject affinity is not a visibility gate / 排序近期全局记忆，主体贴合程度不是可见性条件。"""
    if not subject:
        return []
    levels = ("fact", "scene", "detail") if profile else ("scene", "detail", "fact")
    rows = []
    for art in pool:
        try:
            if art.header.family != "memory":
                continue
            if str(art.header.scope or "") not in ("shared", "private"):
                continue
            if str(art.payload.get("level") or "") not in levels:
                continue
            subject_id = str(art.header.subject_id or "")
            said_by = str(art.header.said_by or "")
            if subject_id == subject or said_by == subject:
                affinity = 2
            elif subject_id == "owner":
                affinity = 1
            else:
                affinity = 0
            rows.append((affinity, str(art.header.time.created or ""),
                         str(art.header.id), art))
        except Exception:
            continue
    rows.sort(key=lambda row: (row[0], row[1], row[2]), reverse=True)
    return [row[3] for row in rows[:max(0, limit)]]
