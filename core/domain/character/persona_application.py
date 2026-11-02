"""Identify an explicitly applied pack and compare settings without storage or artwork I/O.

识别明确应用的人格包并比较设定，不访问存储或插画文件。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from .persona import persona_payload_from_file

_REFERENCE = re.compile(r"^(official|mine)/[a-z0-9][a-z0-9._-]{1,63}$")
_DIGEST = re.compile(r"^[a-f0-9]{64}$")


def content_digest(value: object) -> str:
    """Hash canonical JSON / 对规范 JSON 计算摘要。"""
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def settings_digest(payload: dict[str, Any]) -> str:
    """Compare name, text, style and boundaries separately from pack assets / 将姓名、正文、风格和边界与包资源分开比较。"""
    return content_digest({"name": payload.get("persona_name", ""),
                           "text": payload.get("text", ""),
                           "style": payload.get("style", {}),
                           "boundaries": payload.get("boundaries", [])})


def artwork_digest(bundle: dict) -> str | None:
    """Hash validated artwork bytes represented as canonical base64 / 对已验证插画的规范 base64 计算摘要。"""
    art = bundle.get("artwork")
    return hashlib.sha256(art["dataBase64"].encode("ascii")).hexdigest() if art else None


def make_application(reference: str, bundle: dict) -> dict:
    """Record the namespaced identity and reviewed baseline of a validated pack / 记录已验证包的集合身份和已核对基线。"""
    if not _REFERENCE.fullmatch(reference):
        raise ValueError("人格包标识无效")
    seed = bundle["seed"]
    return {"reference": reference, "version": seed["version"],
            "pack_digest": content_digest(bundle),
            "settings_digest": settings_digest(persona_payload_from_file(seed)),
            "artwork_digest": artwork_digest(bundle)}


def application_status(payload: dict) -> dict | None:
    """Expose only complete explicit associations; legacy or malformed records remain unknown / 只展示完整明确关联，旧记录或无效记录保持未知。"""
    raw = payload.get("pack_application")
    if not isinstance(raw, dict) or set(raw) != {
        "reference", "version", "pack_digest", "settings_digest", "artwork_digest"
    }:
        return None
    if (not isinstance(raw["reference"], str) or not _REFERENCE.fullmatch(raw["reference"])
            or not isinstance(raw["version"], str) or not raw["version"]):
        return None
    for key in ("pack_digest", "settings_digest", "artwork_digest"):
        value = raw[key]
        if key == "artwork_digest" and value is None:
            continue
        if not isinstance(value, str) or not _DIGEST.fullmatch(value):
            return None
    return {"reference": raw["reference"], "version": raw["version"],
            "packDigest": raw["pack_digest"], "settingsDigest": raw["settings_digest"],
            "currentSettingsDigest": settings_digest(payload), "artworkDigest": raw["artwork_digest"]}
