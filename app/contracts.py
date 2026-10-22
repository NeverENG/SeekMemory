from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DialogueTurn:
    session_id: str
    speaker_id: str
    role: str
    text: str
    at: str = ""
    source_id: str = ""
    topic_id: str = ""


@dataclass(frozen=True)
class ExtractionState:
    source_id: str
    turn_id: str
    session_id: str
    topic_id: str = ""
    state: str = "pending"
    attempts: int = 0
    last_error: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class RecallRequest:
    query: str
    session_id: str
    speaker_id: str = ""
    owner_id: str = ""
    is_private: bool = False
    present_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecallResult:
    block: str = ""
    mode: str = "none"
    picked_ids: tuple[str, ...] = ()
    chars: int = 0
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class WriteOutcome:
    written: int = 0
    skipped: int = 0
    ids: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    model_failed: bool = False


@dataclass(frozen=True)
class ChatRequest:
    session_id: str
    system_prompt: str
    prompt: str
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int = 800
    json_mode: bool = False


@dataclass(frozen=True)
class ChatResponse:
    text: str
    model: str = ""
    provider_id: str = ""
    usage_in: int = 0
    usage_cached: int = 0
    usage_out: int = 0
    response_id: str = ""
    latency_ms: int = 0
