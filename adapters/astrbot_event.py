"""AstrBot 事件 → RuntimeInput 的纯映射。

只做字段翻译，不做判断；矩阵平台（Telegram/微信/抖音/B站）以后各自实现同形状的
映射函数，运行时只消费 RuntimeInput。

设计口径见 `docs/zh/architecture/event-contract.md`：不引入 HostEvent 中间层。
"""

from __future__ import annotations

from typing import Any

try:
    from ..app.runtime.contracts import RuntimeInput
except ImportError:  # 作为顶层包导入（脚本 / 测试）
    from app.runtime.contracts import RuntimeInput


def _text(event: Any) -> str:
    """取纯文本；没有 message_str 时退回 str()。"""
    raw = getattr(event, "message_str", "")
    return str(raw or "").strip()


def _mentioned(event: Any) -> bool:
    """AstrBot 用 is_at_or_wake_command 表示被 @ 或唤醒前缀命中。"""
    return bool(getattr(event, "is_at_or_wake_command", False))


def _scene(event: Any) -> str:
    """私聊 / 群 / 评论区；未知平台默认按群处理。"""
    try:
        if bool(event.is_private_chat()):
            return "private"
    except Exception:  # noqa: BLE001 - 未知宿主默认群聊
        pass
    scene = str(getattr(event, "scene", "") or "")
    if scene in ("group", "channel", "thread", "comment"):
        return scene
    return "group"


def _role(event: Any, owner_id: str) -> str:
    """主人优先；管理员角色由宿主给出。"""
    sender = str(getattr(event, "sender_id", "") or getattr(event, "get_sender_id", lambda: "")())
    if owner_id and sender == owner_id:
        return "owner"
    role = str(getattr(event, "role", "") or "")
    if role in ("admin", "owner", "member", "bot", "system"):
        return role
    return "member"


def _at(event: Any) -> float:
    """事件时间；取不到就返回 0，由运行时用当前时钟。"""
    value = getattr(event, "created_at", 0.0)
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def to_runtime_input(
    event: Any,
    *,
    session_id: str = "",
    owner_id: str = "",
    names: tuple[str, ...] = (),
    unread_count: int = 0,
    unread_seq: int = 0,
) -> RuntimeInput:
    """把一个宿主事件映射成运行时输入；字段缺失时按保守默认值处理。"""
    text = _text(event)
    called = any(name and name in text for name in names)
    return RuntimeInput(
        session_id=str(session_id or getattr(event, "unified_msg_origin", "") or ""),
        text=text,
        event_time=_at(event),
        received_at=_at(event),
        speaker_id=str(
            getattr(event, "sender_id", "")
            or getattr(event, "get_sender_id", lambda: "")()
            or ""
        ),
        private=_scene(event) == "private",
        mentioned=_mentioned(event),
        question="?" in text or "？" in text,
        unread_count=max(0, int(unread_count)),
        unread_seq=max(0, int(unread_seq)),
        scene=_scene(event),
        conversation_id=str(getattr(event, "group_id", "") or ""),
        thread_id=str(getattr(event, "thread_id", "") or ""),
        self_id=str(getattr(event, "self_id", "") or ""),
        role=_role(event, owner_id),
        addressed=_mentioned(event) or called,
        reply_to_me=bool(getattr(event, "reply_to_self", False)),
        event_id=str(getattr(event, "message_id", "") or ""),
        kind="message",
    )
