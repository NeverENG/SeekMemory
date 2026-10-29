"""Decode existing legacy objects without writes or time conversion.

解析既有旧对象，不执行写入或时间转换。
"""
from __future__ import annotations

import json

def json_object(raw: object) -> dict:
    """Decode an object or return an empty object for invalid legacy data / 解析对象，对无效的旧数据返回空对象。"""
    value = raw
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}

