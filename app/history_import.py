"""Application contracts for reading administrator-provided chat history."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


class HistoryFileError(ValueError):
    """The uploaded history file cannot be safely interpreted."""


@dataclass(frozen=True)
class HistoryMember:
    platform_id: str
    account_name: str = ""


@dataclass(frozen=True)
class HistoryMessage:
    row_number: int
    ordinal: int
    sender_id: str
    external_message_id: str
    timestamp: float
    at: str
    content: str
    reply_to_message_id: str = ""
    byte_offset: int = 0
    byte_length: int = 0


@dataclass(frozen=True)
class HistoryInspection:
    format: str
    version: str
    platform: str
    conversation_type: str
    name: str
    members: tuple[HistoryMember, ...]
    sender_counts: dict[str, int]
    message_rows: int
    accepted_messages: int
    skipped_rows: int
    missing_id_rows: int
    first_at: str
    last_at: str
    warnings: tuple[dict[str, int | str], ...]
