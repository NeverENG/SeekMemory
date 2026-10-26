"""Pure role mapping and Source/topic construction for ChatLab imports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

try:
    from ..app.contracts import DialogueTurn
    from ..app.history_import import HistoryInspection
    from ..app.ports import HistoryReader
    from ..app.topic_policy import assign_topic
    from ..core.source import Source, SourceQueueEntry, make_import_source_id
except ImportError:
    from app.contracts import DialogueTurn
    from app.history_import import HistoryInspection
    from app.ports import HistoryReader
    from app.topic_policy import assign_topic
    from core.source import Source, SourceQueueEntry, make_import_source_id


@dataclass(frozen=True)
class RoleSelection:
    bot_platform_id: str
    target_platform_id: str
    target_umo: str
    bot_member_id: str = ""
    target_member_id: str = ""


@dataclass(frozen=True)
class TopicCorrection:
    source_ids: tuple[str, ...]
    topic_id: str


def resolve_roles(
    inspection: HistoryInspection, selection: RoleSelection
) -> dict[str, str]:
    """Resolve exactly two active file speakers, without nickname inference."""
    bot_account = selection.bot_platform_id.strip()
    target_account = selection.target_platform_id.strip()
    target_umo = selection.target_umo.strip()
    if not bot_account or not target_account or not target_umo:
        raise ValueError("请填写 Bot 平台账号、目标用户和目标私聊 UMO")
    if len(target_umo) > 300 or any(ord(char) < 32 for char in target_umo):
        raise ValueError("目标 UMO 格式无效")
    if ":FriendMessage:" not in target_umo or "GroupMessage" in target_umo:
        raise ValueError("目标 UMO 必须是 AstrBot 私聊会话")

    speakers = set(inspection.sender_counts)
    if len(speakers) != 2:
        raise ValueError("文件必须且只能包含 Bot 与一个目标用户两位发言者")
    bot_member = selection.bot_member_id.strip() or (
        bot_account if bot_account in speakers else ""
    )
    target_member = selection.target_member_id.strip() or (
        target_account if target_account in speakers else ""
    )
    if not bot_member or not target_member:
        raise ValueError("无法按平台 ID 唯一匹配，请在预览中明确选择 Bot 与目标用户")
    if bot_member == target_member:
        raise ValueError("Bot 与目标用户不能选择同一成员")
    if bot_member not in speakers or target_member not in speakers:
        raise ValueError("所选成员没有出现在有效消息中")
    if bot_member != bot_account or target_member != target_account:
        raise ValueError("平台账号 ID 必须与预览中确认的成员 ID 一致")
    if speakers != {bot_member, target_member}:
        raise ValueError("文件中存在 Bot 与目标用户以外的发言者")
    _, marker, umo_target = target_umo.rpartition(":FriendMessage:")
    if not marker or umo_target != target_member:
        raise ValueError("目标私聊 UMO 的用户 ID 必须与确认的目标成员一致")
    return {bot_member: "assistant", target_member: "user"}


def reply_targets(path: str, reader: HistoryReader) -> set[str]:
    """Collect only IDs referenced by valid replies for bounded topic state."""
    return {
        message.reply_to_message_id
        for message in reader.iter_messages(path)
        if message.reply_to_message_id
    }


def iter_source_entries(
    path: str,
    reader: HistoryReader,
    *,
    roles: dict[str, str],
    target_umo: str,
    platform: str,
    referenced_ids: set[str],
) -> Iterator[SourceQueueEntry | TopicCorrection]:
    """Build stable Sources and apply the shared live topic policy."""
    previous: DialogueTurn | None = None
    user_topics: dict[str, str] = {}
    waiting: dict[str, list[str]] = {}
    canonical_umo = target_umo.strip()

    for message in reader.iter_messages_sorted(path):
        role = roles.get(message.sender_id)
        if role not in {"user", "assistant"}:
            raise ValueError("文件包含未映射的发言者")
        source_id = make_import_source_id(
            format_id="chatlab",
            conversation_id=canonical_umo,
            external_message_id=message.external_message_id,
        )
        reply_to = (
            make_import_source_id(
                format_id="chatlab",
                conversation_id=canonical_umo,
                external_message_id=message.reply_to_message_id,
            )
            if message.reply_to_message_id
            else None
        )
        parent = None
        if role == "assistant" and message.reply_to_message_id:
            parent_topic = user_topics.get(message.reply_to_message_id)
            if parent_topic:
                parent = DialogueTurn(
                    canonical_umo, "", "user", "", message.at, topic_id=parent_topic
                )

        turn = DialogueTurn(
            canonical_umo,
            message.sender_id,
            role,
            message.content,
            message.at,
            source_id,
            "",
            source_id,
            reply_to,
        )
        turn = assign_topic(turn, previous, parent)
        source = Source(
            id=source_id,
            turn_id=source_id,
            session_id=canonical_umo,
            speaker_id=message.sender_id,
            role=role,
            text=message.content,
            at=message.at,
            reply_to=reply_to,
            metadata={
                "origin": {
                    "format_id": "chatlab",
                    "canonical_conversation_id": canonical_umo,
                    "external_message_id": message.external_message_id,
                    "platform": platform,
                }
            },
        )

        if role == "assistant" and message.reply_to_message_id and parent is None:
            waiting.setdefault(message.reply_to_message_id, []).append(source_id)
        if role == "user" and message.external_message_id in referenced_ids:
            user_topics[message.external_message_id] = turn.topic_id
            late_replies = waiting.pop(message.external_message_id, [])
            if late_replies:
                yield TopicCorrection(tuple(late_replies), turn.topic_id)

        previous = turn
        yield SourceQueueEntry(source, turn.topic_id)
