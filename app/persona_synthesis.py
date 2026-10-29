"""Pure persona requests and validation; MaintenanceService owns evidence selection, model calls and commits.

纯人格请求及校验，MaintenanceService 负责证据选择、模型调用和提交。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

try:
    from .contracts import ChatRequest
except ImportError:  # Standalone import / 独立测试以仓库为导入根目录。
    from app.contracts import ChatRequest

MAX_PERSONA_CHARS = 20000
MAX_STYLE_JSON = 20000
MAX_BOUNDARIES = 32
MAX_BOUNDARY_CHARS = 300
MAX_CHANGE_REASON = 300

_SYSTEM = """You revise the active persona of a long-lived companion AI.
Use the current persona as the authoritative base and make an incremental update.
Keep identity, voice and boundaries coherent. Do not invent private facts or
quote chat records. Return JSON only with exactly these keys:
{"persona": "updated persona text", "style": {}, "boundaries": [], "change_reason": "short reason"}
Do not output Markdown or any text outside the JSON object."""


@dataclass(frozen=True)
class PersonaEvidence:
    """Caller-supplied evidence summary; selection and disclosure happen upstream / 调用方提供的证据概述，筛选和披露在上游完成。"""

    id: str
    kind: str
    text: str
    source_ids: tuple[str, ...] = ()


def _bounded_text(value: Any, maximum: int) -> str:
    return str(value or "").strip()[:maximum]


def build_persona_request(
    current_payload: dict[str, Any],
    evidence: list[PersonaEvidence],
    *,
    max_evidence_chars: int = 2400,
) -> ChatRequest:
    """Build a bounded request from persona and evidence summaries; do not call a model / 按人格及证据概述构造有界请求，不调用模型。"""
    evidence_lines: list[str] = []
    used = 0
    for item in evidence:
        text = _bounded_text(item.text, 500)
        line = f"- [{item.kind}] {text}"
        if used + len(line) > max_evidence_chars:
            break
        evidence_lines.append(line)
        used += len(line)
    style = current_payload.get("style")
    boundaries = current_payload.get("boundaries")
    prompt = json.dumps(
        {
            "current_persona": {
                "name": current_payload.get("persona_name", ""),
                "text": _bounded_text(current_payload.get("text"), MAX_PERSONA_CHARS),
                "style": style if isinstance(style, dict) else {},
                "boundaries": boundaries if isinstance(boundaries, list) else [],
            },
            "evidence": evidence_lines,
            "instruction": "Make an incremental improvement to this persona.",
        },
        ensure_ascii=False,
    )
    return ChatRequest(
        session_id="dream:persona",
        system_prompt=_SYSTEM,
        prompt=prompt,
        temperature=0.4,
        max_tokens=1600,
        json_mode=True,
    )


def _strip_fence(text: str) -> str:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return raw


def parse_persona_draft(raw: str, current_payload: dict[str, Any]) -> dict[str, Any] | None:
    """Validate JSON and safety bounds; unchanged text returns None, invalid output raises ValueError.

    校验 JSON 和安全限额，文本未变返回空，非法输出抛 ValueError。
    """
    try:
        data = json.loads(_strip_fence(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError("persona synthesis 输出不是合法 JSON") from exc
    if not isinstance(data, dict) or set(data) != {
        "persona", "style", "boundaries", "change_reason"
    }:
        raise ValueError("persona synthesis 输出字段不合法")
    persona = data.get("persona")
    if not isinstance(persona, str) or not persona.strip():
        raise ValueError("persona synthesis 输出缺少 persona")
    persona = persona.strip()
    if len(persona) > MAX_PERSONA_CHARS:
        raise ValueError("persona synthesis 输出人格文本过长")
    style = data.get("style")
    if not isinstance(style, dict):
        raise ValueError("persona synthesis 输出 style 必须是对象")
    try:
        if len(json.dumps(style, ensure_ascii=False)) > MAX_STYLE_JSON:
            raise ValueError("persona synthesis 输出 style 过大")
    except (TypeError, ValueError) as exc:
        raise ValueError("persona synthesis 输出 style 无法序列化") from exc
    boundaries = data.get("boundaries")
    if not isinstance(boundaries, list) or len(boundaries) > MAX_BOUNDARIES:
        raise ValueError("persona synthesis 输出 boundaries 不合法")
    clean_boundaries = []
    for item in boundaries:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("persona synthesis 输出 boundaries 含空值")
        value = item.strip()
        if len(value) > MAX_BOUNDARY_CHARS:
            raise ValueError("persona synthesis 输出 boundary 过长")
        clean_boundaries.append(value)
    reason = data.get("change_reason")
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("persona synthesis 输出缺少 change_reason")
    reason = reason.strip()
    if len(reason) > MAX_CHANGE_REASON:
        raise ValueError("persona synthesis 输出 change_reason 过长")
    if persona == str(current_payload.get("text") or "").strip():
        return None
    return {
        "persona": persona,
        "style": dict(style),
        "boundaries": clean_boundaries,
        "change_reason": reason,
    }
