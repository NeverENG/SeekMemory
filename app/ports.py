"""Required external capabilities / 应用层要求外部提供的能力。

Declarations and explicit exports only; no I/O implementation.
仅声明与集中导出，不实现读写；资源由组装方创建、管理和关闭。
Runtime and callback definitions retain their existing import paths.
运行时与回调沿用原定义；集中入口不表示内部职责已经整理完成。
"""

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


# Model and retrieval / 模型调用与检索。
@runtime_checkable
class ChatModel(Protocol):
    """Complete one provider-neutral request / 完成一次通用模型请求。"""

    async def complete(self, request: ChatRequest) -> ChatResponse:
        """Complete one request; failures raise rather than fabricate a response / 完成一次请求，失败抛异常，不伪造回复。"""
        ...


@runtime_checkable
class Retriever(Protocol):
    """Rank a supplied Artifact pool / 从调用方提供的记忆池中检索候选。"""

    def retrieve(self, query: str, pool: list[Artifact]) -> list[RetrievalCandidate]:
        """Rank the supplied memory pool without persistence / 对提供的记忆池排序，不执行持久化。"""
        ...


@runtime_checkable
class SourceStore(Protocol):
    """Append immutable evidence and read it by time/ID / 追加不可变证据，并按时间或编号读取。"""

    def append_sources(self, sources: list[Source]) -> int:
        """Append immutable evidence and return newly inserted rows / 追加不可变证据并返回新增行数。"""
        ...
    def recent_sources(self, *, since: str, limit: int) -> list[Source]:
        """Read evidence within the supplied time and count limits / 在给定时间和数量限制内读取证据。"""
        ...
    def source_umo(self, source_id: str) -> str:
        """Read one Source's originating session / 读取一条原始消息的来源会话。"""
        ...
    def source_umos(self, source_ids: list[str]) -> dict[str, str]:
        """Read originating sessions for the supplied Source IDs / 批量读取原始消息编号对应的来源会话。"""
        ...
    def sources_by_ids(self, source_ids: list[str]) -> dict[str, Source]:
        """Read immutable evidence by ID without reinterpretation / 按编号读取不可变证据，不重新解释。"""
        ...


@runtime_checkable
class ArtifactStore(Protocol):
    """Read memory revisions and commit version/evidence/ledger together.

    读取记忆版本；commit 原子保存版本、证据及账本，失败不得更新缓存。
    Separate graph/parent calls are not part of commit / 连接和父节点调用不属于该原子提交。
    """

    def commit(self, art: Artifact, *, expected_revision: int, op: str,
               reason: str = "", source_ids: tuple[str, ...] = (),
               state_events: tuple[StateEvent, ...] = ()) -> None:
        """Atomically commit revision, evidence, events and ledger; conflicts raise, cache is separate.

        原子提交版本、证据、事件及账本，冲突抛异常，缓存另行更新。
        """
        ...
    def commit_many(
        self,
        writes: list[tuple[Artifact, int, tuple[str, ...]]],
        *,
        op: str,
        reason: str = "",
    ) -> None:
        """Atomically commit the supplied revision/evidence group / 原子提交给定的一组版本和证据。"""
        ...
    def get(self, node_id: str) -> Artifact | None:
        """Read the current revision, or None if absent / 读取当前版本，不存在返回空。"""
        ...
    def by_source_ids(self, source_ids: list[str]) -> list[Artifact]:
        """Find current interpretations linked to Source IDs / 查找关联指定原始消息的当前解释。"""
        ...
    def list(self, family: str | None = None,
             state: str | None = None) -> list[Artifact]:
        """Read memory by optional family and state filters / 按可选类型和状态筛选记忆。"""
        ...
    def list_recent(self, limit: int) -> list[Artifact]:
        """Read a bounded list of recent memories / 限量读取近期记忆。"""
        ...
    def list_impressions(self, limit: int, offset: int = 0) -> list[Artifact]:
        """Read one bounded impression page / 限量读取一页印象。"""
        ...
    def count_impressions(self) -> int:
        """Count current impressions / 统计当前印象数。"""
        ...
    def count(self, family: str | None = None) -> int:
        """Count memory, optionally within one family / 统计记忆数，可限定类型。"""
        ...
    def edges_between(self, node_ids: list[str], limit: int) -> list[ArtifactEdge]:
        """Read bounded connections within the supplied IDs / 限量读取指定编号之间的连接。"""
        ...
    def history(self, node_id: str) -> list[dict]:
        """Read stored revisions for one memory / 读取一条记忆的已保存版本。"""
        ...
    def add_edge(self, src: str, dst: str, kind: str, weight: float) -> None:
        """Write one connection independently of revision commit / 独立于版本提交写入一条连接。"""
        ...
    def edges_of(self, node_id: str) -> list[tuple[str, str, float]]:
        """Read both ends as (other ID, kind, weight); direction is omitted / 返回双向连接的（另一端编号、类型、权重），不含方向。"""
        ...
    def set_parent(self, node_id: str, parent_id: str | None) -> None:
        """Set only the parent field; does not maintain edges / 仅设置父字段，不维护连接。"""
        ...
    def inspect_record(self, node_id: str) -> dict:
        """Read version, evidence and ledger detail for inspection / 读取供检查的版本、证据及账本细节。"""
        ...


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
    """Active-memory read model; put only after commit / 有效记忆的派生读视图，提交成功后才能更新。"""

    artifacts: ArtifactStore

    @property
    def version(self) -> int:
        """Read a monotonic change marker for derived indices / 读取供派生索引使用的单调变化标记。"""
        ...
    def load(self) -> None:
        """Rebuild active-memory indices from storage / 从存储重建有效记忆索引。"""
        ...
    def put(self, art: Artifact) -> None:
        """Update active memory after commit; remove inactive values / 提交后更新有效记忆，非有效值移出缓存。"""
        ...
    def get(self, node_id: str) -> Artifact | None:
        """Read cached memory; a miss does not prove storage absence / 读取缓存记忆，未命中不表示数据库不存在。"""
        ...
    def active(self, family: str | None = None) -> list[Artifact]:
        """Read cached active memory with an optional family filter / 读取缓存中的有效记忆，可限定类型。"""
        ...
    def by_level(self, level: str) -> list[Artifact]:
        """Read cached active memory at one abstraction level / 读取指定抽象层级的有效缓存记忆。"""
        ...
    def by_subject(self, subject_id: str) -> list[Artifact]:
        """Read cached active memory about one subject / 读取关于指定主体的有效缓存记忆。"""
        ...
    def remove(self, node_id: str) -> None:
        """Remove one cached memory and its index entries / 移除缓存记忆及对应索引。"""
        ...
    def size(self) -> int:
        """Count cached active memory / 统计有效缓存记忆数。"""
        ...


@runtime_checkable
class MetricsStore(Protocol):
    """Read capacity measurements / 读取容量用量。"""

    def capacity_usage(self, now: str = "") -> dict[str, Any]:
        """Read current capacity measurements / 读取当前容量用量。"""
        ...


@runtime_checkable
class LedgerStore(Protocol):
    """Read and verify the business ledger / 读取并校验业务账本。"""

    def entries(self) -> list[Any]:
        """Read business ledger entries / 读取业务账本记录。"""
        ...
    def verify(self) -> bool:
        """Check the stored ledger chain / 校验已保存的账本链。"""
        ...


@runtime_checkable
class ExtractionStore(Protocol):
    """Queue Source references and record extraction outcomes / 排队原始消息引用，记录抽取结果与重试。"""

    def enqueue_extraction(
        self,
        source: Source,
        topic_id: str,
        created_at: str = "",
        *,
        deferred: bool = False,
    ) -> bool:
        """Queue a Source reference, preserving evidence and deferred admission / 排队原始消息引用，保留证据及延后接纳状态。"""
        ...
    def pending_extractions(self, now: str = "") -> list[dict]:
        """Read pending rows eligible at the supplied time / 读取指定时刻可处理的待抽取行。"""
        ...
    def queue_counts(self) -> dict[str, int]:
        """Count rows by queue state / 按队列状态统计行数。"""
        ...
    def release_deferred(self, limit: int = 50) -> int:
        """Admit a bounded set of deferred rows / 限量接纳延后处理行。"""
        ...
    def ready_extraction_ids(self, now: str = "") -> set[str]:
        """Read Source IDs ready at the supplied time / 读取指定时刻可处理的原始消息编号。"""
        ...
    def mark_extraction_succeeded(self, source_ids: list[str]) -> int:
        """Mark completed Source IDs without deleting evidence / 标记已完成的原始消息编号，不删除证据。"""
        ...
    def mark_extraction_failed(
        self,
        source_ids: list[str],
        error_type: str,
        *,
        max_attempts: int = 5,
        now: str = "",
    ) -> int:
        """Retain failed rows with bounded attempts and retry time / 保留失败行，并记录有上限的次数及重试时间。"""
        ...


# Console data sources / 控制台所需数据；no HTTP or UI types / 不含传输或界面类型。
from .console_ports import (
    DreamRunStore, # get/begin/finish/recent: daily run lifecycle / 每日整理生命周期。
    DreamJournal,  # recent: read recent daily runs / 读取近期夜间整理记录。
    PersonaPacks,  # catalog/read/save/remove: manage seed packs / 列出、读取、保存及删除人格包。
)

# Runtime dependencies / 运行时所需能力；implementations are injected / 实现由外部注入。
from .runtime.contracts import (
    ActionPort,         # execute: perform a host action / 执行宿主动作。
    ActionSink,         # append: persist content-free action audit / 保存无正文的动作审计。
    Clock,              # __call__: UTC epoch seconds / 返回 UTC 时间戳秒数。
    MemoryContextPort,  # build_context: read-only memory context / 只读构建记忆上下文。
    MessageSender,      # send: compatibility text delivery / 兼容的文本发送接口。
    ModelGateway,       # complete: runtime model text call / 运行时的模型文本调用。
    ProactivePolicy,    # evaluate: pure eligibility decision / 纯规则判断主动发言条件。
    SessionStateStore,  # get/put: mutable scheduling state, not memory / 读取和保存调度状态，不是记忆。
    TraceSink,          # record: diagnostic event, not business audit / 记录诊断事件，不替代业务审计。
)
from .runtime.topics import TopicSource  # candidates: read proactive topics / 读取主动话题候选。
from .runtime.recorder import (
    CheckpointSink,  # record: enqueue a memory hit / 排队一次记忆命中。
    EpisodeWriter,   # record: accept one run record / 接收一条运行记录。
    PendingSink,     # add: add a Source-backed extraction view / 建立待抽取的原始消息视图。
    SourceSink,      # append_sources: append raw evidence / 追加原始证据。
)
from .runtime.episode import EpisodeSink  # append: persist one run record / 保存一条运行记录。
from .runtime.tracing import TraceWriter  # append: write one diagnostic row / 写入一条诊断记录。
from .runtime.contracts.ports import ActionRepository, EpisodeRepository, StateRepository

# Daily-cycle callbacks / 夜间整理所需回调；the two clock shapes are deliberately distinct / 两种时钟返回值不同。
from .dream import (
    Clock as DreamClock,  # datetime, unlike runtime Clock's float / 返回日期时间对象，不是运行时时钟的秒数。
    FlushFn,             # Extract a bounded batch and return counts / 限量抽取批次并返回数量。
    Log,                 # Emit a status message / 输出状态消息。
    MaintainFn,          # Run maintenance and return a summary / 执行维护并返回汇总。
    PendingFn,           # Count pending input / 统计待处理输入。
    UsageFn,             # Read cumulative model usage / 读取累计模型用量。
)

__all__ = [
    "ChatModel", "Retriever", "SourceStore", "ArtifactStore", "TreeArtifactStore", "TreeCache",
    "ArtifactCache", "MetricsStore", "LedgerStore", "ExtractionStore", "DreamJournal", "PersonaPacks",
    "ActionPort", "ActionSink", "Clock", "MemoryContextPort", "MessageSender", "ModelGateway",
    "ProactivePolicy", "SessionStateStore", "TraceSink", "TopicSource",
    "CheckpointSink", "EpisodeWriter", "PendingSink", "SourceSink", "EpisodeSink", "TraceWriter",
    "DreamClock", "FlushFn", "Log", "MaintainFn", "PendingFn", "UsageFn",
    "DreamRunStore", "ActionRepository", "EpisodeRepository", "StateRepository",
]
