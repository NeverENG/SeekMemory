"""Host-neutral runtime ports and memory-context DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
class Clock(Protocol):
    """Wall-clock source used by the runtime; returns UTC epoch seconds."""

    def __call__(self) -> float: ...

class TraceSink(Protocol):
    def record(self, kind: str, status: str, context: dict[str, Any] | None = None) -> None: ...


@dataclass(frozen=True)
class MemoryContextRequest:
    """Host-neutral request for read-only memory context."""

    session_id: str
    query: str = ""
    source_id: str = ""
    speaker_id: str = ""
    private: bool = False
    event_time: float = 0.0
    received_at: float = 0.0
    now: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class MemoryContext:
    text: str = ""
    info: dict[str, Any] = field(default_factory=dict)


class MemoryContextPort(Protocol):
    def build_context(self, request: MemoryContextRequest) -> MemoryContext: ...


class ModelGateway(Protocol):
    async def complete(
        self, session_id: str, prompt: str, system_prompt: str | None = None
    ) -> str: ...


class MessageSender(Protocol):
    async def send(self, session_id: str, text: str) -> bool: ...


class StateRepository(Protocol):
    """Store raw session payloads; failures raise / 保存原始会话状态，失败抛异常。"""

    def get(self, session_id: str) -> dict[str, Any]:
        """Read a payload, or an empty map / 读取状态，不存在返回空映射。"""
        ...

    def put(self, session_id: str, payload: dict[str, Any]) -> None:
        """Persist one payload before returning / 返回前保存一份状态。"""
        ...


class EpisodeRepository(Protocol):
    """Append content-free run audit payloads / 追加不含正文的运行审计。"""

    def append(self, episode: dict[str, Any]) -> str:
        """Return the persisted ID; raise on failure / 返回保存的编号，失败抛异常。"""
        ...


class ActionRepository(Protocol):
    """Append idempotent action transitions / 追加可去重的动作迁移记录。"""

    def append_action(self, action: dict[str, Any]) -> bool:
        """Return whether inserted; raise on failure / 返回是否新增，失败抛异常。"""
        ...

