from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

try:
    from ..core.artifact import Artifact
    from ..core.graph import ArtifactEdge
    from ..core.source import Source
    from ..core.versioning import StateEvent
    from ..core.retrieval import RetrievalCandidate
    from .contracts import ChatRequest, ChatResponse
except ImportError:
    from core.artifact import Artifact
    from core.graph import ArtifactEdge
    from core.source import Source
    from core.versioning import StateEvent
    from core.retrieval import RetrievalCandidate
    from app.contracts import ChatRequest, ChatResponse


@runtime_checkable
class ChatModel(Protocol):
    async def complete(self, request: ChatRequest) -> ChatResponse: ...


@runtime_checkable
class Retriever(Protocol):
    def retrieve(self, query: str, pool: list[Artifact]) -> list[RetrievalCandidate]: ...


@runtime_checkable
class SourceStore(Protocol):
    def append_sources(self, sources: list[Source]) -> int: ...
    def recent_sources(self, *, since: str, limit: int) -> list[Source]: ...
    def source_umo(self, source_id: str) -> str: ...
    def source_umos(self, source_ids: list[str]) -> dict[str, str]: ...
    def sources_by_ids(self, source_ids: list[str]) -> dict[str, Source]: ...


@runtime_checkable
class ArtifactStore(Protocol):
    def commit(self, art: Artifact, *, expected_revision: int, op: str,
               reason: str = "", source_ids: tuple[str, ...] = (),
               state_events: tuple[StateEvent, ...] = ()) -> None: ...
    def commit_many(
        self,
        writes: list[tuple[Artifact, int, tuple[str, ...]]],
        *,
        op: str,
        reason: str = "",
    ) -> None: ...
    def get(self, node_id: str) -> Artifact | None: ...
    def by_source_ids(self, source_ids: list[str]) -> list[Artifact]: ...
    def list(self, family: str | None = None,
             state: str | None = None) -> list[Artifact]: ...
    def list_recent(self, limit: int) -> list[Artifact]: ...
    def list_impressions(self, limit: int, offset: int = 0) -> list[Artifact]: ...
    def count_impressions(self) -> int: ...
    def count(self, family: str | None = None) -> int: ...
    def edges_between(self, node_ids: list[str], limit: int) -> list[ArtifactEdge]: ...
    def history(self, node_id: str) -> list[dict]: ...
    def add_edge(self, src: str, dst: str, kind: str, weight: float) -> None: ...
    def edges_of(self, node_id: str) -> list[tuple[str, str, float]]: ...
    def set_parent(self, node_id: str, parent_id: str | None) -> None: ...
    def inspect_record(self, node_id: str) -> dict: ...


class TreeArtifactStore(Protocol):
    """Storage needed by Tree; separate calls are not one transaction / 树所需存储，多次调用不是一个整体事务。"""

    def get(self, node_id: str) -> Artifact | None:
        """Read the current revision, or None if absent / 读取当前版本，不存在返回空。"""
        ...

    def commit(self, art: Artifact, *, expected_revision: int, op: str,
               reason: str = "", source_ids: tuple[str, ...] = (),
               state_events: tuple = ()) -> None:
        """Atomically save revision/evidence/ledger; expected 0 creates, conflicts raise VersionError.

        原子保存版本、证据和账本；新建预期版本为 0，版本冲突抛 VersionError；不更新缓存。
        """
        ...

    def list(self, family: str | None = None,
             state: str | None = None) -> list[Artifact]:
        """Read by optional family/state; None omits that filter / 按类型、状态筛选，空值表示不限制该项。"""
        ...

    def edges_of(self, node_id: str) -> list[tuple[str, str, float]]:
        """Read (other ID, kind, weight) from both ends; direction omitted / 双向查询连接，返回另一端、类型、权重，不含方向。"""
        ...

    def add_edge(self, src: str, dst: str, kind: str, weight: float) -> None:
        """Upsert one edge; does not change the parent column / 写入或更新一条连接，不修改父节点字段。"""
        ...

    def set_parent(self, node_id: str, parent_id: str | None) -> None:
        """Set/clear only the parent column; absent child is a no-op / 仅设置或清空父字段，不维护连接；子节点不存在则无操作。"""
        ...


class TreeCache(Protocol):
    """Optional active-memory cache; no persistence / 可选的有效记忆缓存，不负责持久化。"""

    def get(self, node_id: str) -> Artifact | None:
        """Read cached value; None does not prove storage absence / 读取缓存；未命中不表示数据库中不存在。"""
        ...

    def put(self, art: Artifact) -> None:
        """Replace active values, remove inactive ones; call after commit / 更新有效记忆，移除非有效记忆；提交成功后调用。"""
        ...

    def by_level(self, level: str) -> list[Artifact]:
        """Read cached active values at one abstraction level / 读取指定抽象层级的有效缓存记忆。"""
        ...


@runtime_checkable
class ArtifactCache(Protocol):
    artifacts: ArtifactStore

    @property
    def version(self) -> int: ...
    def load(self) -> None: ...
    def put(self, art: Artifact) -> None: ...
    def get(self, node_id: str) -> Artifact | None: ...
    def active(self, family: str | None = None) -> list[Artifact]: ...
    def by_level(self, level: str) -> list[Artifact]: ...
    def by_subject(self, subject_id: str) -> list[Artifact]: ...
    def remove(self, node_id: str) -> None: ...
    def size(self) -> int: ...


@runtime_checkable
class MetricsStore(Protocol):
    def capacity_usage(self, now: str = "") -> dict[str, Any]: ...


@runtime_checkable
class LedgerStore(Protocol):
    def entries(self) -> list[Any]: ...
    def verify(self) -> bool: ...


@runtime_checkable
class ExtractionStore(Protocol):
    def enqueue_extraction(
        self,
        source: Source,
        topic_id: str,
        created_at: str = "",
        *,
        deferred: bool = False,
    ) -> bool: ...
    def pending_extractions(self, now: str = "") -> list[dict]: ...
    def queue_counts(self) -> dict[str, int]: ...
    def release_deferred(self, limit: int = 50) -> int: ...
    def ready_extraction_ids(self, now: str = "") -> set[str]: ...
    def mark_extraction_succeeded(self, source_ids: list[str]) -> int: ...
    def mark_extraction_failed(
        self,
        source_ids: list[str],
        error_type: str,
        *,
        max_attempts: int = 5,
        now: str = "",
    ) -> int: ...
