"""Map supplied host events into runtime data without business policy or persistence.

将给定宿主事件映射为运行时数据，不实现业务规则或持久化。
"""

from __future__ import annotations

import math
from typing import Any, Callable

try:
    from ...app.runtime.contracts import RuntimeInput
except ImportError:  # Top-level package / 顶层包。
    from app.runtime.contracts import RuntimeInput


def _text(event: Any) -> str:
    """取纯文本；没有 message_str 时退回 str()。"""
    raw = getattr(event, "message_str", "")
    return str(raw or "").strip()


def _mentioned(event: Any) -> bool:
    """真正 @ 她才算 mentioned。

    不能用 ``is_at_or_wake_command``：wake_prefix 为空字符串时 AstrBot 会把每条群消息
    都标成唤醒，按那个判断等于"所有消息都在 @ 她"。这里只认消息组件里指向 self_id 的 At。
    """
    try:
        me = str(getattr(event, "self_id", "") or "")
        if not me:
            try:
                me = str(event.get_self_id() or "")
            except Exception:  # noqa: BLE001 - Optional host getter / 可选宿主读取函数。
                me = ""
        for comp in event.get_messages() or ():
            if type(comp).__name__ == "At" and str(getattr(comp, "qq", "")) == me:
                return True
    except Exception:  # noqa: BLE001 - Missing mention metadata stays false / 缺少点名信息时保持否。
        return False
    return False


def _scene(event: Any) -> str:
    """Map existing private/group/comment markers; preserve the unknown fallback / 映射既有私聊、群聊及评论标记，保留未知回退。"""
    try:
        if bool(event.is_private_chat()):
            return "private"
    except Exception:  # noqa: BLE001 - Preserve unknown-host group fallback / 保留未知宿主群聊回退。
        pass
    scene = str(getattr(event, "scene", "") or "")
    if scene in ("group", "channel", "thread", "comment"):
        return scene
    return "group"


def _identity(event: Any, attribute: str, getter: str = "") -> str:
    """Read host identity metadata with the existing fallback / 按既有回退读取宿主身份元数据。"""
    try:
        return str(getattr(event, attribute, "") or getattr(event, getter, lambda: "")() or "")
    except Exception:  # Isolate host metadata failures / 隔离宿主元数据失败。
        return ""


def event_id(event: Any) -> str:
    """Read one stable platform event identity for callback correlation / 读取用于回调关联的稳定平台事件身份。"""
    try:
        return str(getattr(getattr(event, "message_obj", None), "message_id", "")
                   or getattr(event, "message_id", "") or "")
    except Exception:
        return ""


def _role(event: Any, owner_id: str) -> str:
    """Map owner first, then existing host-admin role metadata / 先映射所有者，再映射既有宿主管理员角色元数据。"""
    sender = _identity(event, "sender_id", "get_sender_id")
    if owner_id and sender == owner_id:
        return "owner"
    role = str(getattr(event, "role", "") or "")
    if role in ("admin", "owner", "member", "bot", "system"):
        return role
    return "member"


def _at(event: Any) -> float:
    """Read a known event instant or zero using the existing timestamp mapping / 按既有时间戳映射读取已知事件时刻或零。"""
    value = getattr(event, "created_at", 0.0)
    try:
        at = float(value or 0.0)
        return at if math.isfinite(at) and at >= 0 else 0.0
    except (TypeError, ValueError, OverflowError):
        return 0.0


def to_runtime_input(
    event: Any,
    *,
    session_id: str = "",
    owner_id: str = "",
    names: tuple[str, ...] = (),
    unread_count: int = 0,
    unread_seq: int = 0,
    received_at: float | None = None,
    clock: Callable[[], float] | None = None,
) -> RuntimeInput:
    """Reduce a host event to existing runtime fields using supplied clock / 以给定时钟将宿主事件简化为既有运行时字段。"""
    text = _text(event)
    scene = _scene(event)
    called = any(name and name in text for name in names)
    return RuntimeInput(
        session_id=str(session_id or getattr(event, "unified_msg_origin", "") or ""),
        text=text,
        event_time=_at(event),
        received_at=(
            float(clock()) if received_at is None and clock is not None else
            (0.0 if received_at is None else received_at)
        ),
        speaker_id=_identity(event, "sender_id", "get_sender_id"),
        private=scene == "private",
        mentioned=_mentioned(event),
        question="?" in text or "？" in text,
        unread_count=unread_count if type(unread_count) is int and unread_count >= 0 else 0,
        unread_seq=unread_seq if type(unread_seq) is int and unread_seq >= 0 else 0,
        scene=scene,
        conversation_id=_identity(event, "group_id", "get_group_id"),
        thread_id=str(getattr(event, "thread_id", "") or ""),
        self_id=_identity(event, "self_id", "get_self_id"),
        role=_role(event, owner_id),
        addressed=_mentioned(event) or called,
        reply_to_me=bool(getattr(event, "reply_to_self", False)),
        event_id=event_id(event),
        kind="message",
    )
