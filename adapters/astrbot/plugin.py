"""Own AstrBot resource composition and lifecycle; keep construction and cleanup order visible.

管理 AstrBot 资源组装及生命周期，明确构造和清理顺序。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
from pathlib import Path

from astrbot.api import logger, star
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from ...app.budget import budget_from_config
from ...app.checkpoint import CheckpointManager
from ...app.cache_repair import CacheRepairs
from ...app.dream import DreamCycle
from ...app.runtime import (
    AgentRuntime,
    RepoEpisodeStore,
    RepoStateStore,
    EpisodeRecorder,
    JsonStateStore,
    JsonlEpisodeStore,
    MemoryContext,
    MemoryContextRequest,
    ActionExecutor,
    ActionLedger,
    DefaultAttentionPolicy,
    DefaultProactivePolicy,
    RepoActionSink,
    RunContext,
    RuntimeWorker,
    Scheduler,
    ToolPolicy,
)
from ...app.runtime.tracing import RunTracer
from ...core.domain.operations.capacity import CapacityGovernor, CapacityThresholds, load_thresholds
from ...core.domain.memory.graph import Graph
from ...services import (
    AccessPolicy,
    AccessService,
    BackgroundService,
    CapacityService,
    IngestService,
    MaintenanceService,
    ManagementService,
    RecallService,
    ServiceCollection,
    StatusService,
    TreeService,
)
from ...perceive.model import ProviderChatModel
from ...recall.retriever import HybridRetriever
from .actions import AstrBotActionPort
from .model import AstrBotModelGateway
from .context import SeekMemoryContextAdapter
from ...store.cache import Cache
from ...store import Store, open_store
from ...store.run_trace import TraceStore
from ...webui.jobs import Jobs
from ...webui.journal import Journal
from .web import WebRoutes
from ...webui.trace import Trace
from .attention import AttentionHooks
from .hooks import AstrBotHooks
from .runtime import AstrBotRuntimeAdapter
from .time import AstrBotBuffer, AstrBotRunRecorder, AstrBotSourceView
from .topics import AstrBotTopicSource
from ..persona_packs import FilePersonaPacks
from ..relationship_policy import (
    RelationshipInteractionPolicy,
    RelationshipReader,
    settings_from_config,
)

class AstrBotPlugin(star.Star):
    """Own resource composition and lifecycle; handlers use explicit host bindings / 管理资源组装及生命周期，处理函数使用明确宿主依赖。"""

    def __init__(self, context: star.Context, config: dict | None = None) -> None:
        super().__init__(context, config)
        self.context = context
        self.cfg = config or {}
        self.clock = time.time
        self.hooks = AstrBotHooks(self)
        self.attention = AttentionHooks(self)
        self.ready = False
        self.services: ServiceCollection | None = None
        self.store: Store | None = None
        self.cache: Cache | None = None
        self.tree: TreeService | None = None
        self.graph: Graph | None = None
        self.hybrid_retriever: HybridRetriever | None = None
        self.buffer: AstrBotBuffer | None = None
        self.checkpoint: CheckpointManager | None = None
        self.cache_repairs: CacheRepairs | None = None
        self.budget = budget_from_config(self._c)
        self.dream: DreamCycle | None = None
        self.journal: Journal | None = None
        self.trace: Trace | None = None
        self.run_traces: TraceStore | None = None
        self.run_tracer: RunTracer | None = None
        self.tool_policy: ToolPolicy | None = None
        self.jobs: Jobs | None = None
        self.capacity: CapacityGovernor | None = None
        self.relationship_policy: RelationshipInteractionPolicy | None = None
        self._last_runtime_prune_at = 0.0
        self._self_id = ""
        self._started = False
        self._lifecycle_lock = asyncio.Lock()
        self.actions = None
        self.episode_recorder = None
        self.action_ledger = None
        self.action_executor = None
        self.web = None

    async def start(self) -> None:
        """Serialize startup; clean partially created resources on failure/cancellation / 串行启动，失败或取消时清理部分创建的资源。"""
        async with self._lifecycle_lock:
            if self._started:
                return
            try:
                await self._start()
            except BaseException:
                await self._finish_stop()
                raise

    async def _start(self) -> None:
        """Construct the existing resource graph in dependency order, then register host routes / 按依赖顺序构造既有资源图，再注册宿主路由。"""
        if self._started:
            return
        self.ready = False
        self.services = None
        self.store = None
        self.cache = None
        self.tree = None
        self.graph = None
        self.hybrid_retriever = None
        self.buffer = None
        self.checkpoint = None
        self.dream = None
        self.relationship_policy = None
        self.data_path = (
            Path(str(self._c("db_path", ""))).expanduser()
            if self._c("db_path", "")
            else Path(get_astrbot_plugin_data_path()) / "seekmemory" / "memory.db"
        )
        self.journal = Journal(self.data_path.parent / "lifecycle.jsonl")
        self.trace = Trace()
        self.run_traces = TraceStore(
            self.data_path.parent / "run_traces.jsonl",
            retention_days=self._c("trace_retention_days", 7),
            max_rows=self._c("trace_max_rows", 5000),
        )
        self.run_tracer = RunTracer(self.run_traces)
        self.tool_policy = ToolPolicy(
            allowed_prefixes=("memory_", "search_memory", "query_memory")
        )
        self.actions = AstrBotActionPort(self.context)
        self.jobs = Jobs(self.journal)
        artifact_limit = max(1, int(self._c("max_episodes", 500)))
        self.capacity = CapacityGovernor(self._thresholds(artifact_limit))
        self._last_runtime_prune_at = 0.0
        self._init_engine()
        if not self.ready:
            await self._stop()
            return
        recall = RecallService(
            cache_repairs=self.cache_repairs,
            cache=self.cache,
            graph=self.graph,
            artifacts=self.store.artifacts if self.store is not None else None,
            sources=self.store.sources if self.store is not None else None,
            budget=self.budget,
            config=self._c,
            owner_umo=lambda: self.owner_umo,
            hybrid_retriever=self.hybrid_retriever,
            log=lambda msg: logger.info(f"[seekmemory] {msg}"),
        )
        management = ManagementService(
            artifacts=self.store.artifacts if self.store is not None else None,
            sources=self.store.sources if self.store is not None else None,
            ledger=self.store.ledger if self.store is not None else None,
            cache=self.cache,
            recall_service=recall,
            packs=FilePersonaPacks(Path(__file__).resolve().parents[2] / "persona_seeds",
                                   self.data_path.parent / "persona_packs"),
            dreams=self.store.dreams if self.store is not None else None,
        )
        if self.store is not None:
            state_store = RepoStateStore(self.store.runtime_state)
            self.episode_recorder = EpisodeRecorder(RepoEpisodeStore(self.store.runtime_episodes))
        else:
            state_store = JsonStateStore(
                str(self.data_path.parent / "runtime_state.json")
            )
            self.episode_recorder = EpisodeRecorder(
                JsonlEpisodeStore(str(self.data_path.parent / "runtime_episodes.jsonl"))
            )
        self.action_ledger = (
            ActionLedger(RepoActionSink(self.store.runtime_episodes))
            if self.store is not None else None
        )
        self.action_executor = ActionExecutor(
            self.actions, self.action_ledger, clock=self.clock
        )
        recorder = AstrBotRunRecorder(
            sources=self.store.sources if self.store is not None else None,
            buffer=self.buffer,
            checkpoint=self.checkpoint,
            episodes=self.episode_recorder,
            cache=self.cache,
            clock=self.clock,
        )
        runtime = AgentRuntime(
            state_store,
            policy=DefaultAttentionPolicy(
                followup_rounds=int(self._c("attention_followup_rounds", 3)),
                owner_always_reply=bool(self._c("attention_owner_always_reply", True)),
            ),
            trace=self.trace,
            clock=self.clock,
            memory_context=SeekMemoryContextAdapter(self._runtime_memory_context),
            context_recorder=SeekMemoryContextAdapter(self._runtime_memory_context, self._record_memory_context),
            wait_seconds=(
                int(self._c("runtime_wait_seconds", 5))
                if bool(self._c("runtime_gate_enabled", False)) else 0
            ),
            model_gateway=AstrBotModelGateway(self.context),
            action_executor=self.action_executor,
            recorder=recorder,
        )
        self.relationship_policy = RelationshipInteractionPolicy(
            RelationshipReader(self.cache),
            settings_from_config(
                self._c,
                lambda key: logger.warning(
                    f"[seekmemory] normalized relationship config: {key}"
                ),
            ),
        )
        if self.store is not None:
            try:
                self.store.runtime_episodes.prune(
                    retention_days=int(self._c("runtime_episode_retention_days", 30)),
                    max_rows=int(self._c("runtime_episode_max_rows", 5000)),
                )
            except Exception:
                pass
            self._last_runtime_prune_at = self.clock()
            self.dream = DreamCycle(
                self.store.dreams, self._c,
                log=lambda msg: logger.info(f"[seekmemory] {msg}"),
            )
        maintenance = MaintenanceService(
            cache_repairs=self.cache_repairs,
            artifacts=self.store.artifacts if self.store is not None else None,
            sources=self.store.sources if self.store is not None else None,
            cache=self.cache,
            journal=self.journal,
            task_id=lambda: self.jobs.task_id,
            logger=logger,
            config=self._c,
            persona_model=self._persona_model,
        )
        scheduler = Scheduler(runtime.store)
        capacity = CapacityService(
            metrics=self.store.metrics if self.store is not None else None,
            extraction=self.store.extraction if self.store is not None else None,
            maintenance=maintenance,
            trace=self.trace,
            journal=self.journal,
            governor=self.capacity,
            config=self._c,
            logger=logger,
            on_release=self._reload_buffer,
        )
        ingest = IngestService(
            cache_repairs=self.cache_repairs,
            buffer=self.buffer,
            artifacts=self.store.artifacts if self.store is not None else None,
            sources=AstrBotSourceView(self.store.sources) if self.store is not None else None,
            extraction=self.store.extraction if self.store is not None else None,
            cache=self.cache,
            graph=self.graph,
            journal=self.journal,
            config=self._c,
            provider_for=self.context.get_using_provider_async,
            owner_id=lambda: (
                self.owner_umo.split(":")[-1] if self.owner_umo else ""
            ),
            logger=logger,
        )
        status = StatusService(
            artifacts=self.store.artifacts if self.store is not None else None,
            ledger=self.store.ledger if self.store is not None else None,
        )
        runtime_worker = RuntimeWorker(
            runtime=runtime,
            scheduler=scheduler,
            enabled=lambda: bool(self._c("runtime_gate_enabled", False)),
            session_ids=lambda limit: (
                self.store.runtime_state.sessions(limit=limit)
                if self.store is not None else []
            ),
            run_context=self._make_run_context,
            interval_seconds=lambda: float(self._c("runtime_tick_seconds", 5)),
            max_attempts=lambda: int(self._c("runtime_dispatch_max_attempts", 3)),
            base_seconds=lambda: float(self._c("runtime_dispatch_backoff_seconds", 2)),
            trace=self.trace,
            clock=self.clock,
            proactive_policy=DefaultProactivePolicy(
                enabled=bool(self._c("proactive_enabled", False))
            ),
            topic_source=AstrBotTopicSource(self.buffer),
        )
        background = BackgroundService(
            jobs=self.jobs,
            checkpoint=self.checkpoint,
            buffer=self.buffer,
            capacity=capacity,
            ingest=ingest,
            maintenance=maintenance,
            dream=self.dream,
            runtime_worker=runtime_worker,
            journal=self.journal,
            config=self._c,
            logger=logger,
            context_writer=recall,
        )
        self.services = ServiceCollection(
            access_service=AccessService(
                AccessPolicy(
                    mode=str(self._c("open_to", "owner_only")),
                    owner_umo=self.owner_umo,
                    trusted_ids=frozenset(self.trusted_ids),
                    observe_groups=bool(self._c("observe_groups", True)),
                )
            ),
            recall_service=recall,
            ingest_service=ingest,
            capacity_service=capacity,
            maintenance_service=maintenance,
            management_service=management,
            status_service=status,
            background_service=background,
            runtime=runtime,
            runtime_worker=runtime_worker,
        )
        self.web = WebRoutes(self)
        self.web.register()
        self._started = True

    def _c(self, key: str, default):
        """Read existing plugin configuration with its supplied fallback / 按给定回退读取既有插件配置。"""
        try:
            v = self.cfg.get(key, default)
            if v is None:
                return default
            return type(default)(v)
        except Exception:
            return default

    def _threshold_overrides(self) -> dict:
        """Read existing capacity overrides from a dict or JSON object / 从字典或 JSON 对象读取既有容量覆盖值。"""
        raw = self.cfg.get("capacity_thresholds", "")
        if isinstance(raw, dict):
            return raw
        try:
            data = json.loads(str(raw or "").strip() or "{}")
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _thresholds(self, artifact_limit: int) -> CapacityThresholds:
        """Combine existing capacity defaults, overrides and environment settings / 组合既有容量默认、覆盖及环境设置。"""
        values = dict(self._threshold_overrides())
        values.setdefault("artifact_pressured_count", max(1, int(artifact_limit * 0.8)))
        values.setdefault("artifact_saturated_count", max(1, artifact_limit))
        return load_thresholds(values)

    def _admit_deferred(self) -> bool:
        """Ask the existing capacity service for deferred admission / 向既有容量服务请求延后接纳决策。"""
        return self.services.capacity_service.admit_deferred()

    @property
    def owner_umo(self) -> str:
        """Read the configured owner session / 读取已配置的所有者会话。"""
        return str(self._c("owner_umo", ""))

    @property
    def trusted_ids(self) -> set[str]:
        """Read configured trusted sender identities / 读取已配置的可信发送者身份。"""
        raw = str(self._c("trusted", ""))
        return {x.strip() for x in raw.replace("，", ",").split(",") if x.strip()}

    def _init_engine(self) -> None:
        """Construct store/cache/buffer graph resources; contain ordinary startup failure / 构造存储、缓存、缓冲及图资源，隔离普通启动失败。"""
        try:
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            self.store = open_store(str(self.data_path))
            self.cache = Cache(self.store.artifacts)
            self.cache.load()
            self.tree = TreeService(self.store.artifacts, self.cache)
            self.graph = Graph(self.store.artifacts)
            self.hybrid_retriever = HybridRetriever(self.graph, self.cache)
            self.buffer = AstrBotBuffer(
                str(self.data_path.parent / "pending.json"),
                extraction=self.store.extraction,
                clock=self.clock,
            )
            migrated = self.buffer.migrate_legacy()
            if self.buffer.load_error:
                self.journal.record(
                    "capacity",
                    "warning",
                    "pending file was quarantined",
                    context={"error": self.buffer.load_error},
                )
            self.ready = True
            self.cache_repairs = CacheRepairs(self.store.artifacts, self.cache)
            self.checkpoint = CheckpointManager(
                self.store.artifacts, self.cache, int(self._c("checkpoint_seconds", 1800)),
                cache_repairs=self.cache_repairs
            )
            self.journal.record(
                "plugin", "ready", f"已加载 {self.cache.size()} 条有效记忆"
            )
            if migrated:
                self.journal.record(
                    "capacity",
                    "info",
                    "旧 pending 已迁移为 Source 投影",
                    context={"rows": migrated},
                )
            logger.info(
                f"[seekmemory] 已加载 {self.cache.size()} 条记忆，"
                f"待抽取 {len(self.buffer.items)} 条"
            )
        except Exception as e:  # noqa: BLE001
            self.ready = False
            self.journal.record("plugin", "failed", "记忆引擎初始化失败", error=e)
            logger.error(f"[seekmemory] 初始化失败，记忆功能降级：{type(e).__name__}")

    def _runtime_memory_context(self, request: MemoryContextRequest) -> MemoryContext:
        """Read disclosed memory through the pure recall entry / 通过纯召回入口读取已披露记忆。"""
        block, info = self._recall_block(
            request.query, request.session_id, request.private, request.speaker_id
        )
        return MemoryContext(text=block, info=info)

    def _record_memory_context(self, context: MemoryContext) -> None:
        """Record actual inclusion using the recall writer / 通过召回写入入口记录实际包含情况。"""
        self.services.recall_service.record_context_injection(context.text, context.info)

    def _calls_path(self) -> str:
        """Read the content-free call log path beside the database / 读取数据库旁的无正文调用日志路径。"""
        return str(self.data_path.parent / "calls.jsonl")

    async def _persona_model(self):
        """Resolve the existing persona provider lazily for one bounded call / 延迟解析既有人格提供方以执行一次有界调用。"""
        provider = await self.context.get_using_provider_async(self.owner_umo)
        return ProviderChatModel(provider)

    def _recall_block(
        self, text: str, umo: str = "", private: bool = False, speaker: str = ""
    ) -> tuple[str, dict]:
        """Query recall with the current capacity degradation input / 按当前容量降级输入查询召回。"""
        return self.services.recall_service.query(
            text,
            umo,
            private,
            speaker,
            degraded=self.services.capacity_service.degrade_recall,
        )

    async def stop(self) -> None:
        """Serialize shutdown through the lifecycle lock / 通过生命周期锁串行关闭。"""
        async with self._lifecycle_lock:
            await self._finish_stop()

    async def _finish_stop(self) -> None:
        """Shield cleanup to completion before re-raising cancellation / 保护清理直至完成，再重新传播取消。"""
        cleanup = asyncio.create_task(self._stop())
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError:
            await cleanup
            raise

    async def _stop(self) -> None:
        """Stop tasks/routes, finish writeback attempts and close owned storage in order / 按顺序停止任务及路由、完成补写尝试并关闭自有存储。"""
        self.ready = False
        operations = [
            (self.services.background_service, "stop") if self.services else (None, "stop"),
            (self.jobs, "close"), (self.web, "close"), (self.buffer, "save"),
            (self.checkpoint, "flush"), (self.store, "close"),
        ]
        cancellation = None
        for resource, method in operations:
            if resource is None:
                continue
            try:
                result = getattr(resource, method)()
                if inspect.isawaitable(result):
                    await result
            except asyncio.CancelledError as exc:
                cancellation = exc
            except Exception as exc:
                if self.journal is not None:
                    self.journal.record("plugin", "failed", "resource cleanup failed", error=exc)
        if self.journal is not None and any(resource is not None for resource, _ in operations):
            self.journal.record("plugin", "stopped", "plugin resources released")
        for name in (
            "services", "store", "cache", "tree", "graph", "hybrid_retriever",
            "buffer", "checkpoint", "cache_repairs", "dream", "jobs", "web", "actions",
            "episode_recorder", "action_ledger", "action_executor",
            "tool_policy", "capacity", "run_traces", "run_tracer", "trace",
        ):
            setattr(self, name, None)
        self.hooks.reset()
        self._self_id = ""
        self._started = False
        if cancellation is not None:
            raise cancellation

    def _reload_buffer(self) -> None:
        """Reload the current Source-backed projection after deferred release / 在延后释放后重载当前原始消息视图。"""
        if self.buffer is not None:
            self.buffer.reload()

    def _make_run_context(self, session_id: str, now: float) -> RunContext:
        """Read latest session source and current bot identity for a background run / 读取最新会话原始消息及当前机器人身份以执行后台运行。"""
        source = self.store.sources.latest_user_source(session_id) if self.store is not None else None
        source = source or {}
        return RunContext(
            session_id=session_id,
            text=str(source.get("text") or "").strip(),
            source_id=str(source.get("id") or ""),
            bot_id=str(getattr(self, "_self_id", "") or "bot"),
            event_time=AstrBotRuntimeAdapter.source_event_time(source),
            received_at=now,
        )
