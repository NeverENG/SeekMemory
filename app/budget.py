"""Pure character/message budgets and usage estimates; no tokenizer, model or storage / 纯字数及消息预算与用量估算，不访问分词器、模型或存储。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable

# Estimate 1.6 characters/token plus role overhead / 按 1.6 字/token 估算，另计角色开销。
CHARS_PER_TOKEN = 1.6
MESSAGE_OVERHEAD = 4


@dataclass(frozen=True)
class ContextBudget:
    """Request character/message limits and estimated usage / 请求的字数、消息数限额及估算用量。"""

    injection_chars: int = 600      # Injection limit / 记忆注入上限
    system_chars: int = 1600        # Persona and system text / 人格提示词及系统说明
    group_context_messages: int = 20  # Group message limit / 群聊流水条数上限
    history_messages: int = 24      # History message limit / 历史消息条数上限
    source_recall_enabled: bool = True
    source_recall_hours: int = 12
    source_recall_max_candidates: int = 80

    @property
    def estimate_tokens(self) -> int:
        """Estimate system and injection usage, excluding history / 估算系统及记忆注入用量，不含对话历史。"""
        return estimate_tokens(self.system_chars + self.injection_chars)

    def as_dict(self) -> dict:
        """Return limits and estimated usage for display / 返回供展示使用的限额及估算用量。"""
        data = asdict(self)
        data["estimate_tokens"] = self.estimate_tokens
        return data


def estimate_tokens(chars: int, messages: int = 0) -> int:
    """Estimate tokens from characters and per-message overhead; no tokenizer is used / 按字数及每条消息开销估算用量，不调用分词器。"""
    body = int(max(0, int(chars)) / CHARS_PER_TOKEN)
    return body + MESSAGE_OVERHEAD * max(0, int(messages))


def estimate_messages(texts: list[str]) -> int:
    """Estimate combined message usage / 估算一组消息的总用量。"""
    return estimate_tokens(sum(len(str(t)) for t in texts), len(texts))


def budget_from_config(conf: Callable[[str, object], object]) -> ContextBudget:
    """Normalize supplied config with existing defaults; no host config access / 按既有默认值规整提供的配置，不访问宿主配置对象。"""
    default = ContextBudget()

    def _num(key: str, fallback: int, minimum: int = 1) -> int:
        raw = conf(key, fallback)
        if raw is None or raw == "":
            raw = fallback
        try:
            value = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return fallback
        return max(minimum, value)

    def _bool(key: str, fallback: bool) -> bool:
        value = conf(key, fallback)
        if isinstance(value, str):
            return value.strip().lower() not in ("", "0", "false", "no", "off")
        return bool(value)

    return ContextBudget(
        injection_chars=_num("budget_chars", default.injection_chars),
        system_chars=_num("context_system_chars", default.system_chars),
        group_context_messages=_num(
            "group_context_messages", default.group_context_messages
        ),
        history_messages=_num("history_messages", default.history_messages),
        source_recall_enabled=_bool(
            "source_recall_enabled", default.source_recall_enabled
        ),
        source_recall_hours=_num(
            "source_recall_hours", default.source_recall_hours
        ),
        source_recall_max_candidates=_num(
            "source_recall_max_candidates", default.source_recall_max_candidates
        ),
    )


def clamp_chars(text: str, limit: int) -> tuple[str, int]:
    """Trim near punctuation; return text and original length / 尽量在标点处裁剪，返回文本及原长度。"""
    body = str(text or "")
    size = len(body)
    limit = max(0, int(limit))
    if size <= limit:
        return body, size
    cut = body[:limit]
    for mark in ("。", "；", "，", "\n"):
        index = cut.rfind(mark)
        if index >= limit // 2:
            cut = cut[: index + 1]
            break
    return cut, size
