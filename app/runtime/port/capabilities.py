"""Runtime-required external capabilities; resources belong to composition.

运行时要求的外部能力声明；资源由组装方管理。
"""

from __future__ import annotations

from typing import Any, Protocol

from ..contracts.context import MemoryContext, MemoryContextRequest


class Clock(Protocol):
    """Injected wall-clock source returning UTC epoch seconds / 注入的时钟，返回 UTC 时间戳秒数。"""

    def __call__(self) -> float: ...

class TraceSink(Protocol):
    """Optional content-free diagnostics, separate from business audit / 可选的无正文诊断，与业务审计分开。"""
    def record(self, kind: str, status: str, context: dict[str, Any] | None = None) -> None:
        """Record a diagnostic event; consumers isolate failures / 记录诊断事件，使用方隔离失败。"""
        ...


class MemoryContextPort(Protocol):
    """Read-only access to the existing recall pipeline / 只读访问既有召回流程。"""
    def build_context(self, request: MemoryContextRequest) -> MemoryContext:
        """Build disclosed context without hidden memory writes / 构建已披露上下文，不暗中写入记忆。"""
        ...


class MemoryContextRecorder(Protocol):
    """Record actual context inclusion; no memory-domain semantics in runtime.

    记录实际的上下文包含情况，运行时不包含记忆领域语义。
    """

    def record_context_injection(self, context: MemoryContext) -> None:
        """Record immediately before model invocation, independently of its outcome.

        在模型调用前立即记录，不依赖其结果。
        """
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
