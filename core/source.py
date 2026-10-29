"""Define immutable raw-message evidence, stable identity and validation; no persistence.

定义不可变原始消息证据、稳定编号及校验，不执行保存。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

ROLES = ("user", "assistant", "system", "tool", "external")


def content_hash(text: str) -> str:
    """Hash text with SHA-256 without changing it.

    以 SHA-256 计算文本指纹，不修改文本。
    """
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()


def make_source_id(*, event_id: str = "", session_id: str, speaker_id: str,
                   role: str, text: str, at: str = "") -> str:
    """Hash event identity or message fields into a stable Source identity.

    将事件编号或消息字段哈希为稳定 Source 编号。
    """
    if event_id:
        raw = "\x1f".join((event_id, session_id, speaker_id, role, text))
    else:
        raw = "\x1f".join((session_id, speaker_id, role, at, text))
    return "s_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


@dataclass(frozen=True)
class Source:
    """Describe immutable raw-message evidence and its reply relationship.

    描述不可变原始消息证据及其回复关系。
    """
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
        """Require identity, a supported role and nonempty text; invalid evidence raises ValueError.

        要求编号、受支持角色及非空正文，无效证据抛出 ValueError。
        """
        if not self.id:
            raise ValueError("source id missing")
        if self.role not in ROLES:
            raise ValueError(f"unknown source role: {self.role}")
        if not str(self.text or "").strip():
            raise ValueError("source text empty")

    @property
    def content_hash(self) -> str:
        """Return the raw-message text fingerprint without writing state.

        返回原始消息正文指纹，不写入状态。
        """
        return content_hash(self.text)
