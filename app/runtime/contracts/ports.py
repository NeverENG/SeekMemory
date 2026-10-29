"""Runtime external capability declarations and context data; resources belong to composition.

运行时外部能力声明及上下文数据，资源属于组装方。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
class Clock(Protocol):
    """Injected wall-clock source returning UTC epoch seconds / 注入的时钟，返回 UTC 时间戳秒数。"""

    def __call__(self) -> float: ...

class TraceSink(Protocol):
    """Optional content-free diagnostics, separate from business audit / 可选的无正文诊断，与业务审计分开。"""
    def record(self, kind: str, status: str, context: dict[str, Any] | None = None) -> None:
        """Record a diagnostic event; consumers isolate failures / 记录诊断事件，使用方隔离失败。"""
        ...


@dataclass(frozen=True)
class MemoryContextRequest:
    """Host-neutral input for read-only memory retrieval / 与宿主无关的只读记忆检索输入。"""

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
    """Disclosed context text and diagnostic metadata / 已披露的上下文文本及诊断信息。"""
    text: str = ""
    info: dict[str, Any] = field(default_factory=dict)


class MemoryContextPort(Protocol):
    """Read-only access to the existing recall pipeline / 只读访问既有召回流程。"""
    def build_context(self, request: MemoryContextRequest) -> MemoryContext:
        """Build disclosed context without hidden memory writes / 构建已披露上下文，不暗中写入记忆。"""
        ...


class ModelGateway(Protocol):
    """Runtime model-text capability, distinct from usage-aware ChatModel / 运行时模型文本能力，与返回用量的 ChatModel 区分。"""
    async def complete(
        self, session_id: str, prompt: str, system_prompt: str | None = None
    ) -> str:
        """Generate text for one session; propagate model failures / 为指定会话生成文本，模型失败向上抛出。"""
        ...


class MessageSender(Protocol):
    """Legacy text delivery capability / 旧式文本交付能力。"""
    async def send(self, session_id: str, text: str) -> bool:
        """Return true only for confirmed delivery; false means failure / 仅确认交付返回真，假表示失败。"""
        ...


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

