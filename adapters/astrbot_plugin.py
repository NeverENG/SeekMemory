"""AstrBot host composition for SeekMemory."""

from __future__ import annotations

import json
import time
from pathlib import Path

from astrbot.api import logger, star
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from ..app.budget import budget_from_config
from ..app.checkpoint import CheckpointManager
from ..app.dream import DreamCycle
from ..app.runtime import (
    AgentRuntime,
    RepoEpisodeStore,
    RepoStateStore,
    EpisodeRecorder,
    JsonStateStore,
    JsonlEpisodeStore,
    MemoryContext,
    MemoryContextRequest,
    RunContext,
    RunRecorder,
    RuntimeWorker,
    Scheduler,
    ToolPolicy,
)
from ..app.runtime.tracing import RunTracer
from ..core.capacity import CapacityGovernor, CapacityThresholds, load_thresholds
from ..core.graph import Graph
from ..core.tree import Tree
from ..services import (
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
)
from ..perceive.buffer import Buffer
from ..perceive.model import ProviderChatModel
from ..recall.retriever import HybridRetriever
from ..adapters.astrbot_actions import AstrBotActionPort
from ..adapters.astrbot_model import AstrBotModelGateway
from ..adapters.seekmemory_context import SeekMemoryContextAdapter
from ..store.cache import Cache
from ..store import Store, open_store
from ..store.run_trace import TraceStore
from ..webui.jobs import Jobs
from ..webui.journal import Journal
from ..webui.routes import WebRoutes
from ..webui.trace import Trace
from .astrbot_hooks import AstrBotHooks

class AstrBotPlugin(AstrBotHooks):
    """Composition root and lifecycle owner for the AstrBot host.

    Event handlers live in ``adapters.astrbot_hooks``. This class only builds
    services, exposes the shared plugin state, and starts/stops background work.
    """

    def __init__(self, context: star.Context, config: dict | None = None) -> None:
        super().__init__(context, config)
        self.context = context
        self.cfg = config or {}
        self.ready = False
        self.services: ServiceCollection | None = None
        self.store: Store | None = None
        self.cache: Cache | None = None
        self.tree: Tree | None = None
        self.graph: Graph | None = None
        self.hybrid_retriever: HybridRetriever | None = None
        self.buffer: Buffer | None = None
        self.checkpoint: CheckpointManager | None = None
        self.budget = budget_from_config(self._c)
        self.dream: DreamCycle | None = None
        self.journal: Journal | None = None
        self.trace: Trace | None = None
        self.run_traces: TraceStore | None = None
        self.run_tracer: RunTracer | None = None
        self.tool_policy: ToolPolicy | None = None
        self.jobs: Jobs | None = None
        self.capacity: CapacityGovernor | None = None
        self._last_runtime_prune_at = 0.0
        self._started = False
        self.web = None

    async def start(self) -> None:
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
        recall = RecallService(
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
        recorder = RunRecorder(
            sources=self.store.sources if self.store is not None else None,
            buffer=self.buffer,
            checkpoint=self.checkpoint,
            episodes=self.episode_recorder,
            cache=self.cache,
        )
        runtime = AgentRuntime(
            state_store,
            trace=self.trace,
            clock=time.time,
            memory_context=SeekMemoryContextAdapter(self._runtime_memory_context),
            wait_seconds=(
                int(self._c("runtime_wait_seconds", 5))
                if bool(self._c("runtime_gate_enabled", False)) else 0
            ),
            model_gateway=AstrBotModelGateway(self.context),
            message_sender=self.actions,
            recorder=recorder,
        )
        if self.store is not None:
            try:
                self.store.runtime_episodes.prune(
                    retention_days=int(self._c("runtime_episode_retention_days", 30)),
                    max_rows=int(self._c("runtime_episode_max_rows", 5000)),
                )
            except Exception:
                pass
            self._last_runtime_prune_at = time.time()
            self.dream = DreamCycle(
                self.store.dreams, self._c,
                log=lambda msg: logger.info(f"[seekmemory] {msg}"),
            )
        maintenance = MaintenanceService(
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
            buffer=self.buffer,
            artifacts=self.store.artifacts if self.store is not None else None,
            sources=self.store.sources if self.store is not None else None,
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
        self._started = True
        self.web = WebRoutes(self)
        self.web.register()

    def _c(self, key: str, default):
        try:
            v = self.cfg.get(key, default)
            if v is None:
                return default
            return type(default)(v)
        except Exception:
            return default

    def _threshold_overrides(self) -> dict:
        """Read ``capacity_thresholds`` as a dict or a JSON object string."""
        raw = self.cfg.get("capacity_thresholds", "")
        if isinstance(raw, dict):
            return raw
        try:
            data = json.loads(str(raw or "").strip() or "{}")
        except (TypeError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _thresholds(self, artifact_limit: int) -> CapacityThresholds:
        """Build capacity limits from defaults, config overrides and env keys."""
        values = dict(self._threshold_overrides())
        values.setdefault("artifact_pressured_count", max(1, int(artifact_limit * 0.8)))
        values.setdefault("artifact_saturated_count", max(1, artifact_limit))
        return load_thresholds(values)

    def _admit_deferred(self) -> bool:
        return self.services.capacity_service.admit_deferred()

    @property
    def owner_umo(self) -> str:
        return str(self._c("owner_umo", ""))

    @property
    def trusted_ids(self) -> set[str]:
        raw = str(self._c("trusted", ""))
        return {x.strip() for x in raw.replace("，", ",").split(",") if x.strip()}

    def _init_engine(self) -> None:
        try:
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            self.store = open_store(str(self.data_path))
            self.cache = Cache(self.store.artifacts)
            self.cache.load()
            self.tree = Tree(self.store.artifacts, self.cache)
            self.graph = Graph(self.store.artifacts)
            self.hybrid_retriever = HybridRetriever(self.graph, self.cache)
            self.buffer = Buffer(
                str(self.data_path.parent / "pending.json"), extraction=self.store.extraction
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
            self.checkpoint = CheckpointManager(
                self.store.artifacts, self.cache, int(self._c("checkpoint_seconds", 1800))
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
            self.journal.record("plugin", "failed", "记忆引擎初始化失败", error=e)
            logger.error(f"[seekmemory] 初始化失败，记忆功能降级：{e}")

    def _runtime_memory_context(self, request: MemoryContextRequest) -> MemoryContext:
        block, info = self._recall_block(
            request.query, request.session_id, request.private, request.speaker_id
        )
        return MemoryContext(text=block, info=info)

    def _calls_path(self) -> str:
        """调用日志路径：和数据目录放一起。"""
        return str(self.data_path.parent / "calls.jsonl")

    async def _persona_model(self):
        """Resolve the host provider lazily for one bounded persona call."""
        provider = await self.context.get_using_provider_async(self.owner_umo)
        return ProviderChatModel(provider)

    def _recall_block(
        self, text: str, umo: str = "", private: bool = False, speaker: str = ""
    ) -> tuple[str, dict]:
        return self.services.recall_service.build(
            text,
            umo,
            private,
            speaker,
            degraded=self.services.capacity_service.degrade_recall,
        )

    async def stop(self) -> None:
        if not self._started:
            return
        self.ready = False
        if self.services is not None:
            await self.services.background_service.stop()
        if self.jobs is not None:
            await self.jobs.close()
        if self.web is not None:
            self.web.close()
        if self.buffer is not None:
            self.buffer.save()
        if self.checkpoint is not None:
            self.checkpoint.flush()
        if self.store is not None:
            self.store.close()
            self.store = None
        self.journal.record("plugin", "stopped", "plugin resources released")
        self._started = False

    def _reload_buffer(self) -> None:
        if self.buffer is not None:
            self.buffer.reload()

    def _make_run_context(self, session_id: str, now: float) -> RunContext:
        source = self.store.sources.latest_user_source(session_id) if self.store is not None else None
        source = source or {}
        return RunContext(
            session_id=session_id,
            text=str(source.get("text") or "").strip(),
            source_id=str(source.get("id") or ""),
            bot_id=str(getattr(self, "_self_id", "") or "bot"),
            at=now,
        )
