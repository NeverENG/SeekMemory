"""Normalize portable persona envelopes in memory; only the canonical seed becomes persona configuration.

在内存中整理可移植人格包，只有标准设定成为人格配置。
"""
from __future__ import annotations

import base64
import binascii
import json

from .persona import normalize_persona_file
from .persona_artwork import MAX_ARTWORK_BYTES, validate_artwork

PACK_FORMAT = "seekmemory.persona-pack/v1"
MAX_PACK_BYTES = 3 * 1024 * 1024
MAX_SEED_BYTES = 65536


def normalize_pack(raw: object) -> dict:
    """Accept a legacy seed or a versioned pack without expanding seed fields; invalid input raises ValueError.

    接受旧设定或带版本人格包，不扩展设定字段，无效输入抛出 ValueError。
    """
    if not isinstance(raw, dict):
        raise ValueError("人格包必须是 JSON 对象")
    is_pack = "format" in raw
    if is_pack and (set(raw) != {"format", "seed", "licenseText", "artwork"} or raw["format"] != PACK_FORMAT):
        raise ValueError("人格包格式或版本不受支持")
    seed = normalize_persona_file(raw["seed"] if is_pack else raw)
    if not seed["corpus"]:
        seed.pop("corpus")
    if len(json.dumps(seed, ensure_ascii=False).encode("utf-8")) > MAX_SEED_BYTES:
        raise ValueError("人格设定不能超过 64 KiB")
    license_text = raw["licenseText"] if is_pack else ""
    if not isinstance(license_text, str) or len(license_text.encode("utf-8")) > 65536:
        raise ValueError("许可证文本不能超过 64 KiB")
    artwork = raw["artwork"] if is_pack else None
    if artwork is not None:
        if not isinstance(artwork, dict) or set(artwork) != {"mediaType", "dataBase64"} or artwork["mediaType"] != "image/png":
            raise ValueError("封面仅支持 PNG，不接受路径或远程地址")
        encoded = artwork["dataBase64"]
        if not isinstance(encoded, str) or len(encoded) > 4 * ((MAX_ARTWORK_BYTES + 2) // 3):
            raise ValueError("封面文件过大")
        try:
            image = validate_artwork(base64.b64decode(encoded, validate=True))
        except (binascii.Error, UnicodeError) as exc:
            raise ValueError("封面编码无效") from exc
        if not license_text.strip() or not seed["license"].strip() or not seed["source"].strip():
            raise ValueError("带封面的人格包必须声明许可证、来源和许可文本")
        artwork = {"mediaType": "image/png", "dataBase64": base64.b64encode(image).decode("ascii")}
    return {"format": PACK_FORMAT, "seed": seed, "licenseText": license_text, "artwork": artwork}
