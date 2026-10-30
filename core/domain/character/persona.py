"""Validate authored persona configuration and prepare the single persona chain payload; no file or storage I/O. Authored examples are configuration, never fabricated chat evidence.

校验人工人格配置并准备唯一人格链内容，不读写文件或存储。人工样例是配置，不是伪造的聊天证据。
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

PERSONA_ORIGIN_SEED = "seed"
PERSONA_ORIGIN_DREAM = "dream"
PERSONA_SYNTHESIS_VERSION = "persona.v1"
PERSONA_ORIGINS = (PERSONA_ORIGIN_SEED, PERSONA_ORIGIN_DREAM)
_SEED_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_MAX_TEXT = 20000
_MAX_STYLE = 20000
_MAX_BOUNDARIES = 32
_MAX_BOUNDARY = 300
MIN_CORPUS_EXAMPLES = 12
MIN_CORPUS_CHARS = 1200
_MAX_CORPUS = 128
_MAX_CORPUS_ITEM = 2000
_MAX_CORPUS_JSON = 50000


def _text(value: object, field: str, *, maximum: int, required: bool = False) -> str:
    if not isinstance(value, str):
        if required:
            raise ValueError(f"persona 文件缺少字符串字段：{field}")
        return ""
    text = value.strip()
    if required and not text:
        raise ValueError(f"persona 文件字段不能为空：{field}")
    if len(text) > maximum:
        raise ValueError(f"persona 文件字段过长：{field}")
    return text


def _json_object(value: object, field: str, *, maximum: int) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"persona 文件字段必须是对象：{field}")
    try:
        encoded = json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"persona 文件字段无法序列化：{field}") from exc
    if len(encoded) > maximum:
        raise ValueError(f"persona 文件字段过长：{field}")
    return dict(value)


def _corpus(value: object) -> list[dict[str, str]]:
    """Validate authored dialogue-style examples as configuration, without creating Sources.

    将人工对话风格样例作为配置校验，不创建 Source。
    """
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError("persona 文件 corpus 必须是数组")
    if len(value) < MIN_CORPUS_EXAMPLES:
        raise ValueError(
            f"persona 文件 corpus 至少包含 {MIN_CORPUS_EXAMPLES} 组对话；"
            "语料不足时请省略 corpus 并直接提供 persona，或补充语料"
        )
    if len(value) > _MAX_CORPUS:
        raise ValueError("persona 文件 corpus 条目过多")
    out: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict) or set(item) - {"user", "assistant"}:
            raise ValueError("persona 文件 corpus 条目只允许 user/assistant")
        user = _text(item.get("user"), "corpus.user", maximum=_MAX_CORPUS_ITEM, required=True)
        assistant = _text(
            item.get("assistant"), "corpus.assistant", maximum=_MAX_CORPUS_ITEM, required=True
        )
        out.append({"user": user, "assistant": assistant})
    try:
        encoded = json.dumps(out, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        raise ValueError("persona 文件 corpus 无法序列化") from exc
    if len(encoded) > _MAX_CORPUS_JSON:
        raise ValueError("persona 文件 corpus 过大")
    total_chars = sum(len(item["user"]) + len(item["assistant"]) for item in out)
    if total_chars < MIN_CORPUS_CHARS:
        raise ValueError(
            f"persona 文件 corpus 内容过少：至少 {MIN_CORPUS_CHARS} 字，"
            "语料不足时请省略 corpus 并直接提供 persona"
        )
    return out


def _corpus_hash(corpus: list[dict[str, str]]) -> str:
    encoded = json.dumps(corpus, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _strings(value: object, field: str, *, maximum: int, item_maximum: int) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"persona 文件字段必须是数组：{field}")
    if len(value) > maximum:
        raise ValueError(f"persona 文件字段条目过多：{field}")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"persona 文件字段包含无效文本：{field}")
        text = item.strip()
        if len(text) > item_maximum:
            raise ValueError(f"persona 文件字段条目过长：{field}")
        out.append(text)
    return out


def normalize_persona_file(raw: object) -> dict[str, Any]:
    """Validate and copy normalized persona data; accept persona_text as the legacy alias of persona.

    校验并复制整理后的人格数据，接受 persona_text 作为 persona 的旧别名。
    """
    if not isinstance(raw, dict):
        raise ValueError("persona 文件必须是 JSON 对象")
    allowed = {
        "id", "version", "name", "persona", "persona_text", "style",
        "boundaries", "corpus", "license", "source",
        "content_rating", "locale",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"persona 文件包含未支持字段：{sorted(unknown)}")
    seed_id = _text(raw.get("id"), "id", maximum=64, required=True)
    if not _SEED_ID.fullmatch(seed_id):
        raise ValueError("persona 文件 id 只能使用小写字母、数字、点、下划线和短横线")
    version = _text(raw.get("version"), "version", maximum=32, required=True)
    name = _text(raw.get("name"), "name", maximum=80, required=True)
    persona = raw.get("persona")
    if persona is None:
        persona = raw.get("persona_text")
    text = _text(persona, "persona", maximum=_MAX_TEXT, required=True)
    style = _json_object(raw.get("style"), "style", maximum=_MAX_STYLE)
    boundaries = _strings(
        raw.get("boundaries"), "boundaries", maximum=_MAX_BOUNDARIES,
        item_maximum=_MAX_BOUNDARY,
    )
    corpus = _corpus(raw.get("corpus"))
    return {
        "id": seed_id,
        "version": version,
        "name": name,
        "persona": text,
        "style": style,
        "boundaries": boundaries,
        "corpus": corpus,
        "license": _text(raw.get("license"), "license", maximum=200),
        "source": _text(raw.get("source"), "source", maximum=200),
        "content_rating": _text(raw.get("content_rating"), "content_rating", maximum=32)
        or "general",
        "locale": _text(raw.get("locale"), "locale", maximum=20) or "zh-CN",
    }


def persona_payload_from_file(raw: object) -> dict[str, Any]:
    """Prepare initial persona payload with audit provenance and no fabricated Source links.

    准备含审计来源的初始人格内容，不伪造 Source 引用。
    """
    seed = normalize_persona_file(raw)
    payload = {
        "text": seed["persona"],
        "origin": PERSONA_ORIGIN_SEED,
        "seed_id": seed["id"],
        "seed_version": seed["version"],
        "seed_license": seed["license"],
        "seed_source": seed["source"],
        "persona_name": seed["name"],
        "style": seed["style"],
        "boundaries": seed["boundaries"],
        "corpus_count": len(seed["corpus"]),
        "corpus_hash": _corpus_hash(seed["corpus"]) if seed["corpus"] else "",
        "content_rating": seed["content_rating"],
        "locale": seed["locale"],
    }
    # Keep the authored corpus only on the one-time bootstrap revision. Dream
    # revisions retain its count/hash as provenance and must not duplicate the
    # full corpus in every persona version.
    if seed["corpus"]:
        payload["corpus"] = seed["corpus"]
    return payload


def compose_seed_evolution(base_text: str, behavior_text: str) -> str:
    """Append a deterministic Dream behavior sentence to the authored base text.

    向人工基础文本追加确定的 Dream 行为句子。
    """
    base = str(base_text or "").strip()
    trait = str(behavior_text or "").strip()
    if not base:
        return trait
    if not trait:
        return base
    return f"{base}\n{trait}"


def seed_evolution_matches(text: object, base_text: object, behavior_text: str) -> bool:
    """Check the deterministic text shape of a Dream revision over an authored seed.

    检查人工设定上的 Dream 修订是否符合确定文本形状。
    """
    if not isinstance(text, str) or not isinstance(base_text, str):
        return False
    return text == compose_seed_evolution(base_text, behavior_text)
