"""Convert Artifact rows and persisted values; SQL templates remain compatible aliases.

转换记忆数据行和持久化值，SQL 模板保留兼容别名。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

try:
    from .sqlite import dump_json, load_json_object, pick_dataclass_fields
except ImportError:
    from sqlite import dump_json, load_json_object, pick_dataclass_fields

try:
    from ..core.artifact import Artifact, Header, Lineage, Strength, TimeSpan
except ImportError:
    from core.artifact import Artifact, Header, Lineage, Strength, TimeSpan

try:
    from .artifact_sql import SELECT_SQL, UPSERT_SQL
except ImportError:  # Existing standalone mode / 保留已有的独立导入方式。
    from artifact_sql import SELECT_SQL, UPSERT_SQL


def payload_blob(payload: dict[str, Any]) -> tuple[str, str]:
    """Encode a payload and its content hash without writes / 计算内容的编码及哈希，不执行写入。"""
    content = dump_json(payload)
    return content, hashlib.sha256(content.encode("utf-8")).hexdigest()


def node_values(header: Header, payload: dict[str, Any], now: str,
                blob: str | None = None) -> tuple:
    """Prepare positional node values using the existing persisted layout / 按既有持久化布局准备位置参数。"""
    level, parent = payload.get("level"), payload.get("parent")
    return (
        header.id,
        header.family,
        level if isinstance(level, str) else None,
        parent if isinstance(parent, str) else None,
        blob or payload_blob(payload)[1],
        header.state,
        header.scope,
        dump_json(header.strength),
        dump_json(header.time),
        header.said_by,
        header.shareable,
        header.time.created or now,
        header.time.updated or now,
        int(header.revision),
        dump_json(header.lineage),
        header.subject_id,
    )


def stored_header(header: Header) -> str:
    """Encode the existing version header without format changes / 编码既有版本头部，不改变格式。"""
    return dump_json(
        {
            "state": header.state,
            "scope": header.scope,
            "strength": dump_json(header.strength),
            "time": dump_json(header.time),
            "said_by": header.said_by,
            "revision": int(header.revision),
            "lineage": dump_json(header.lineage),
            "subject_id": header.subject_id,
        }
    )


def row_to_artifact(row: sqlite3.Row | None) -> Artifact | None:
    """Decode one row; absent or malformed content returns None / 解析一行，不存在或内容格式错误时返回空。"""
    if row is None or not row["blob_content"]:
        return None
    try:
        lineage = pick_dataclass_fields(Lineage, load_json_object(row["lineage"]))
        for key in ("sources", "derived_from"):
            lineage[key] = tuple(lineage.get(key) or ())
        header = Header(
            id=str(row["id"]),
            family=str(row["family"]),
            revision=int(row["revision"] or 1),
            state=str(row["state"]),
            scope=str(row["scope"]),
            lineage=Lineage(**lineage),
            strength=Strength(
                **pick_dataclass_fields(Strength, load_json_object(row["strength"]))
            ),
            time=TimeSpan(
                **pick_dataclass_fields(TimeSpan, load_json_object(row["time"]))
            ),
            said_by=str(row["said_by"]),
            shareable=str(row["shareable"]),
            subject_id=str(row["subject_id"] or ""),
        )
        payload = json.loads(row["blob_content"])
    except (TypeError, ValueError, KeyError):
        return None
    return Artifact(header=header, payload=payload if isinstance(payload, dict) else {})
