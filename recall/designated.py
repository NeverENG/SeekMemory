"""Apply private-trigger guards and explicitly record designated context inclusion.

应用私聊及触发词条件，并明确记录指定记忆进入上下文，资源由调用方管理。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

try:  # Plugin namespace / 插件命名空间。
    from ..app.ports import ArtifactStore
    from ..core.artifact import Artifact, revise
except ImportError:  # Top-level package / 顶层包。
    from app.ports import ArtifactStore
    from core.artifact import Artifact, revise

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


def mark_given(artifacts: ArtifactStore, cache: Any, arts: list[Artifact], block: str,
               now: str | None = None) -> int:
    """Explicitly commit given markers only for included designated bodies; isolate per-item failure / 仅为已包含的指定正文明确提交给出标记，逐条隔离失败。"""
    stamp = now or datetime.now().isoformat(timespec="seconds")
    done = 0
    for art in arts:
        if art.header.family != "designated" or already_given(art):
            continue
        body = " ".join(str(art.payload.get("text") or "").split())[:24]
        if not body or body not in block:
            continue
        try:
            updated = revise(art, payload={**art.payload, "given": stamp})
            artifacts.commit(updated, expected_revision=art.header.revision, op="deliver",
                      reason="designated delivered",
                      source_ids=tuple(art.header.lineage.sources))
            cache.put(updated)
        except Exception:  # noqa: BLE001
            continue
        done += 1
    return done
