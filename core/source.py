from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

ROLES = ("user", "assistant", "system", "tool", "external")


def content_hash(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def make_source_id(*, event_id: str = "", session_id: str, speaker_id: str,
                   role: str, text: str, at: str = "") -> str:
    if event_id:
        raw = "\x1f".join((event_id, session_id, speaker_id, role, text))
    else:
        raw = "\x1f".join((session_id, speaker_id, role, at, text))
    return "s_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def make_import_source_id(
    *, format_id: str, conversation_id: str, external_message_id: str
) -> str:
    """Create a stable Source ID for an imported platform message.

    The live event ID helper intentionally retains its existing semantics. This
    separate helper uses a canonical JSON tuple so imported identity is
    unambiguous even when a component contains punctuation used by delimiters.
    """
    identity = [
        str(format_id or "").strip(),
        str(conversation_id or "").strip(),
        str(external_message_id or "").strip(),
    ]
    if not all(identity):
        raise ValueError("import source identity fields are required")
    encoded = json.dumps(identity, ensure_ascii=False, separators=(",", ":"))
    return "si_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Source:
    id: str
    turn_id: str
    session_id: str
    speaker_id: str
    role: str
    text: str
    at: str = ""
    reply_to: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        if not self.id:
            raise ValueError("source id missing")
        if self.role not in ROLES:
            raise ValueError(f"unknown source role: {self.role}")
        if not str(self.text or "").strip():
            raise ValueError("source text empty")

    @property
    def content_hash(self) -> str:
        return content_hash(self.text)


@dataclass(frozen=True)
class SourceQueueEntry:
    """One immutable Source and its extraction topic admission."""

    source: Source
    topic_id: str
