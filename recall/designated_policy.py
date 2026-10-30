"""Evaluate designated trigger and given-state rules without persistence.

判断指定记忆触发及已给出状态，不执行持久化。
"""
from __future__ import annotations

import re
from typing import Any

try:
    from ..core.domain.memory.artifact import Artifact
except ImportError:
    from core.domain.memory.artifact import Artifact

_SPLIT = re.compile(r"[\s,，、/|;；]+")


def triggers_of(art: Artifact) -> list[str]:
    """Read trigger words from supported string/list layouts / 从受支持的字符串或列表布局读取触发词。"""
    raw = art.payload.get("trigger")
    if isinstance(raw, (list, tuple, set)):
        parts = [str(item) for item in raw]
    else:
        parts = _SPLIT.split(str(raw or ""))
    return [part.strip() for part in parts if part.strip()]


def _compact(text: Any) -> str:
    """Remove whitespace for exact trigger comparison / 移除空白以精确比较触发词。"""
    return "".join(str(text or "").split())


def matches(art: Artifact, text: str) -> bool:
    """Match any whitespace-normalized exact trigger substring / 匹配任一规范空白后的精确触发子串。"""
    message = _compact(text)
    return bool(message) and any(_compact(word) in message for word in triggers_of(art))


def already_given(art: Artifact) -> bool:
    """Recognize the existing boolean/timestamp given marker / 识别既有布尔或时间戳给出标记。"""
    return bool(art.payload.get("given"))


def is_private(event: Any) -> bool:
    """Read legacy host privacy; unavailable information fails closed / 读取旧宿主私聊状态，信息不可用时保守拒绝。"""
    try:
        return bool(event.is_private_chat())
    except Exception:  # noqa: BLE001 - Host differences cannot block injection / 宿主差异不能阻塞注入。
        return False


def deliverable(art: Artifact, text: str, private: bool) -> bool:
    """Allow designated bodies only for private triggered unused memory; other families pass / 指定正文仅允许私聊触发且尚未使用的记忆，其他类型通过。"""
    if art.header.family != "designated":
        return True
    return bool(private) and not already_given(art) and matches(art, text)
