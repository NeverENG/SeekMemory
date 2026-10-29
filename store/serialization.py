"""Encode/decode existing persisted values without SQL, clocks or writes.

编解码现有持久化值，不执行 SQL、读取时钟或写入；保留原字节格式和旧值回退行为。
"""
from __future__ import annotations

import dataclasses
import json
from typing import Any

def dump_json(value: Any) -> str:
    """Encode existing JSON with stable key ordering and Unicode preserved / 按稳定键顺序编码既有 JSON，保留 Unicode。"""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        value = dataclasses.asdict(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def load_json_any(raw: Any, default: Any) -> Any:
    """Decode legacy JSON or return the supplied fallback / 解析旧 JSON，失败返回给定回退值。"""
    try:
        return json.loads(raw if raw not in (None, "") else dump_json(default))
    except (TypeError, ValueError):
        return default


def load_json_object(raw: Any) -> dict[str, Any]:
    """Decode a JSON object or return an empty object / 解析 JSON 对象，失败返回空对象。"""
    try:
        data = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def pick_dataclass_fields(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """Keep only fields declared by the supplied dataclass / 仅保留给定数据类声明的字段。"""
    names = {field.name for field in dataclasses.fields(cls)}
    return {key: value for key, value in data.items() if key in names}
