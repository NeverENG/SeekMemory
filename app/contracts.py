"""Shared application data only; no model calls or persistence / 仅定义应用共享数据，不调用模型或执行持久化。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DialogueTurn:
    """Buffered Source projection with explicit reply pairing; not persisted truth / 带明确回复配对的原始消息缓冲投影，不是持久化事实本身。"""

    session_id: str
    speaker_id: str
    role: str
    text: str
    at: str = ""
    source_id: str = ""
    topic_id: str = ""
    turn_id: str = ""
    reply_to: str | None = None


@dataclass(frozen=True)
class ExtractionState:
    """Queue state and retry metadata without message bodies / 不含正文的队列状态与重试信息。"""
    source_id: str
    turn_id: str
    session_id: str
    topic_id: str = ""
    state: str = "pending"
    attempts: int = 0
    next_attempt_at: str = ""
    last_error: str = ""
    created_at: str = ""


@dataclass(frozen=True)
class RecallRequest:
    """Narrow recall input; production RecallService still uses its existing parameters / 窄召回输入，生产 RecallService 仍使用原参数。"""
    query: str
    session_id: str
    speaker_id: str = ""
    owner_id: str = ""
    is_private: bool = False
    present_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RecallResult:
    """Narrow recall result; not yet used by production recall / 窄召回结果，尚未接入生产召回。"""
    block: str = ""
    mode: str = "none"
    picked_ids: tuple[str, ...] = ()
    chars: int = 0
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class WriteOutcome:
    """Write counts, recoverability and model usage for a caller / 向调用方返回写入数量、可恢复性及模型用量。"""
    written: int = 0
    skipped: int = 0
    ids: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    model_failed: bool = False
    retryable: bool = False
    usage_in: int = 0
    usage_cached: int = 0
    usage_out: int = 0


@dataclass(frozen=True)
class ChatRequest:
    """Provider-neutral model input; the caller owns invocation / 与供应商无关的模型输入，由调用方执行调用。"""
    session_id: str
    system_prompt: str
    prompt: str
    model: str | None = None
    temperature: float = 0.0
    max_tokens: int = 800
    json_mode: bool = False


@dataclass(frozen=True)
class ChatResponse:
    """Model text and usage metadata returned by a provider adapter / 供应商转接返回的文本及用量信息。"""
    text: str
    model: str = ""
    provider_id: str = ""
    usage_in: int = 0
    usage_cached: int = 0
    usage_out: int = 0
    response_id: str = ""
    latency_ms: int = 0
