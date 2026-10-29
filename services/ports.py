"""Declare required service capabilities; resources belong to composition.

声明服务所需的外部能力；资源由组装方创建和关闭，此文件不包含业务实现。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from typing import Any, Protocol

try:
    from ..app.contracts import DialogueTurn
    from ..app.ports import (
        ArtifactCache, ArtifactStore, ChatModel, DreamJournal, ExtractionStore,
        LedgerStore, MetricsStore, PersonaPacks, SourceStore, TreeArtifactStore, TreeCache,
    )
except ImportError:
    from app.contracts import DialogueTurn
    from app.ports import (
        ArtifactCache, ArtifactStore, ChatModel, DreamJournal, ExtractionStore,
        LedgerStore, MetricsStore, PersonaPacks, SourceStore, TreeArtifactStore, TreeCache,
    )

Config = Callable[[str, Any], Any]
PersonaModelFactory = Callable[[], Awaitable[ChatModel]]


class LegacyTextModel(Protocol):
    """Existing provider call shape; responses are adapted by perceive.model.

    现有提供方的文本调用形式，响应由 perceive.model 转换；实现由组装方提供。
    """

    async def text_chat(self, *, system_prompt: str, prompt: str) -> Any:
        """Call the legacy provider; failures raise / 调用旧提供方，失败抛错。"""
        ...


ProviderFactory = Callable[[str | None], Awaitable[LegacyTextModel | None]]


class PendingBuffer(Protocol):
    """Project queued Source rows; confirmation must expose write failures.

    投影待处理原始消息；确认操作必须暴露写入失败，不拥有数据库生命周期。
    """

    @property
    def items(self) -> list[DialogueTurn]:
        """Read pending turns / 读取待处理消息。"""
        ...

    def idle_seconds(self) -> float:
        """Read idle duration / 读取空闲时长。"""
        ...

    def oldest_topic_age(self) -> float:
        """Read the oldest topic age / 读取最旧话题的时长。"""
        ...

    def mark_succeeded(self, rows: list[DialogueTurn]) -> int:
        """Confirm only supplied rows; leave newer input intact / 仅确认给定行，保留新输入。"""
        ...

    def mark_failed(self, rows: list[DialogueTurn], error_type: str,
                    *, max_attempts: int = 5) -> int:
        """Retain rows and bounded retry metadata / 保留行及有上限的重试信息。"""
        ...


class ServiceJournal(Protocol):
    """Record content-free diagnostics; not a commit receipt / 记录无正文诊断，不替代提交凭据。"""

    def record(self, kind: str, status: str, message: str, task_id: str = "",
               *, context: dict | None = None, stage: str = "",
               error: BaseException | None = None) -> Any:
        """Record bounded operational metadata / 记录有界的运行元数据。"""
        ...

    def span(self, kind: str, stage: str, **context: Any) -> AbstractContextManager[dict]:
        """Measure an operation and yield its metrics / 测量操作并提供指标容器。"""
        ...


class ServiceLogger(Protocol):
    """Emit operation summaries without payloads / 输出不含正文的操作摘要。"""

    def info(self, message: str) -> None:
        """Emit a success summary / 输出成功摘要。"""
        ...

    def warning(self, message: str) -> None:
        """Emit a failure type or invalid setting / 输出失败类型或无效设置。"""
        ...

    def error(self, message: str) -> None:
        """Emit an operation failure / 输出操作失败。"""
        ...


class BackgroundJobs(Protocol):
    """Serialize scheduled work; the caller owns shutdown / 串行处理定时任务，由调用方管理关闭。"""

    task_id: str

    def submit(self, name: str, operation: Callable[[], Awaitable[Any]]) -> Any:
        """Accept work or raise; do not run it twice / 接纳任务或抛错，不重复执行。"""
        ...


class CapacityTrace(Protocol):
    """Bounded capacity diagnostics, separate from business state / 有界容量诊断，独立于业务状态。"""

    @property
    def count(self) -> int:
        """Count retained trace rows / 统计保留的诊断行数。"""
        ...

    def oldest_age_seconds(self) -> float:
        """Read the age of the oldest trace / 读取最旧诊断的时长。"""
        ...

    def record(self, kind: str, state: str, context: dict) -> Any:
        """Record content-free pressure data / 记录无正文的压力数据。"""
        ...

    def trim(self, limit: int) -> int:
        """Trim retained diagnostics / 裁剪保留的诊断。"""
        ...


__all__ = [
    "ArtifactCache", "ArtifactStore", "ChatModel", "DreamJournal", "ExtractionStore",
    "LedgerStore", "MetricsStore", "PersonaPacks", "SourceStore", "TreeArtifactStore", "TreeCache",
    "Config", "ProviderFactory", "PersonaModelFactory", "LegacyTextModel", "PendingBuffer", "ServiceJournal",
    "ServiceLogger", "BackgroundJobs", "CapacityTrace",
]
