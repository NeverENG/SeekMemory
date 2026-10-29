"""Own periodic tasks and delegate business work to injected services.

管理周期任务并将业务工作委托给注入的服务，其他资源由组装方管理。
"""

from __future__ import annotations

import asyncio
import datetime
from typing import TYPE_CHECKING, Any, Callable

from .ports import BackgroundJobs, PendingBuffer, ServiceJournal, ServiceLogger, WritebackRetrier

if TYPE_CHECKING:
    from .capacity_service import CapacityService
    from .ingest_service import IngestService
    from .maintenance_service import MaintenanceService
    try:
        from ..app.checkpoint import CheckpointManager
        from ..app.dream import DreamCycle
        from ..app.runtime import RuntimeWorker
    except ImportError:
        from app.checkpoint import CheckpointManager
        from app.dream import DreamCycle
        from app.runtime import RuntimeWorker


class BackgroundService:
    """Own scheduled task lifecycle and cadence; delegate memory work to services / 管理定时任务的生命周期与执行频率，将记忆工作委托给服务。"""

    def __init__(
        self,
        *,
        jobs: BackgroundJobs,
        checkpoint: CheckpointManager | None,
        buffer: PendingBuffer | None,
        capacity: CapacityService,
        ingest: IngestService,
        maintenance: MaintenanceService,
        dream: DreamCycle | None,
        runtime_worker: RuntimeWorker,
        journal: ServiceJournal,
        config: Callable[[str, Any], Any],
        logger: ServiceLogger,
        context_writer: WritebackRetrier | None = None,
    ) -> None:
        self.jobs = jobs
        self.checkpoint = checkpoint
        self.buffer = buffer
        self.capacity = capacity
        self.ingest = ingest
        self.maintenance = maintenance
        self.dream = dream
        self.runtime_worker = runtime_worker
        self.journal = journal
        self.config = config
        self.logger = logger
        self.context_writer = context_writer
        self._tasks: list[asyncio.Task] = []

    @property
    def tasks(self) -> list[asyncio.Task]:
        """Read the owned scheduled tasks for lifecycle inspection / 读取自有定时任务以检查生命周期。"""
        return self._tasks

    @property
    def dream_enabled(self) -> bool:
        """Read whether the constructed dream cycle is enabled / 读取已构造的夜间整理流程是否启用。"""
        return bool(self.dream is not None and self.dream.enabled)

    def start(self) -> bool:
        """Start scheduled tasks once; return whether a new set was created / 仅启动一组定时任务，返回是否创建了新任务组。"""
        if self._tasks:
            return False
        operations = [
            self._weekly_loop,
            self._checkpoint_loop,
            self._dream_loop,
            self.runtime_worker.run_forever,
        ]
        if self.dream_enabled:
            operations.append(self._ingest_loop)
        else:
            operations += [self._nightly_loop, self._idle_loop]
        self._tasks = [asyncio.create_task(operation()) for operation in operations]
        self.journal.record("scheduler", "running", "maintenance tasks started")
        return True

    async def stop(self) -> None:
        """Cancel and await all owned tasks; repeated calls are safe / 取消并等待所有自有任务，可重复调用。"""
        tasks = self._tasks
        self._tasks = []
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.retry_writebacks()

    def retry_writebacks(self) -> int:
        """Retry pending persistence independently of extraction/speaking gates.

        独立于抽取及发言开关重试待补写，不调用模型；返回已完成的补偿操作数。
        """
        completed = 0
        for service in (self.ingest, self.runtime_worker, self.context_writer):
            retry = getattr(service, "retry_writebacks", None)
            if retry is None:
                continue
            try:
                completed += int(retry() or 0)
            except Exception as exc:
                self.logger.error(f"[seekmemory] writeback retry failed: {type(exc).__name__}")
        return completed

    async def flush(
        self,
        reason: str,
        limit: int = 0,
        max_calls: int = 0,
        max_tokens: int = 0,
        triage: bool = False,
    ) -> tuple[int, int]:
        decision = self.capacity.observe()
        return await self.ingest.flush(
            reason,
            limit=limit,
            batch_cap=self.capacity.batch_cap(decision),
            max_attempts=self.capacity.thresholds.extraction_max_attempts,
            max_calls=max_calls,
            max_tokens=max_tokens,
            triage=triage,
        )

    def should_flush(self) -> bool:
        """Evaluate pending-input and capacity gates without starting extraction / 评估待处理输入与容量条件，不启动抽取。"""
        decision = self.capacity.observe()
        return self.ingest.should_flush(
            capacity_state=decision.state,
            capacity_actions=decision.actions,
            dream_only=self.dream_enabled,
        )

    async def nightly(self) -> None:
        """Apply capacity maintenance, then request extraction / 执行容量维护，再请求抽取。"""
        decision = self.capacity.observe()
        self.capacity.apply_maintenance(decision)
        await self.flush("nightly")

    async def weekly(self) -> dict:
        """Delegate weekly maintenance and return its summary / 委托每周维护并返回摘要。"""
        return await self.maintenance.weekly()

    async def dream_maintain(self) -> dict:
        """Run the existing weekly maintenance within the dream cycle / 在夜间整理流程中执行现有每周维护。"""
        return await self.weekly()

    async def run_dream(self) -> None:
        """Run bounded extraction and maintenance, then journal the result / 执行有预算上限的抽取与维护，再记录结果。"""
        if self.dream is None or self.buffer is None:
            return
        self.capacity.apply_maintenance(self.capacity.observe())
        result = await self.dream.run(
            flush_once=self.flush,
            pending=lambda: len(self.buffer.items),
            maintain=self.dream_maintain,
            usage=getattr(self.ingest, "usage_snapshot", None),
        )
        self.journal.record(
            "dream",
            result.status,
            f"{result.date}: {result.batches} topics / wrote {result.written}"
            + (f" / {len(result.errors)} errors" if result.errors else ""),
            self.jobs.task_id,
            context={
                "date": result.date,
                "batches": result.batches,
                "written": result.written,
                "errors": list(result.errors),
                "budget": result.summary.get("budget"),
                "usage": result.summary.get("usage"),
            },
        )

    async def _checkpoint_loop(self) -> None:
        """Run checkpoints at the configured cadence; contain ordinary failures / 按配置频率提交检查点，并隔离普通失败。"""
        while True:
            interval = max(60, int(self.config("checkpoint_seconds", 1800)))
            await asyncio.sleep(interval)
            try:
                self.retry_writebacks()
                if self.checkpoint is not None:
                    self.checkpoint.flush()
            except Exception as exc:
                self.logger.error(f"[seekmemory] checkpoint failed: {exc}")

    async def _nightly_loop(self) -> None:
        """Schedule nightly extraction; retain the existing local-time policy / 调度每晚抽取，沿用现有本地时间规则。"""
        while True:
            await asyncio.sleep(
                self.seconds_until(str(self.config("summary_time", "23:50")))
            )
            try:
                self.jobs.submit("nightly", self.nightly)
            except Exception as exc:
                self.logger.error(f"[seekmemory] nightly scheduling failed: {exc}")
                self.journal.record(
                    "scheduler", "failed", "nightly scheduling failed", error=exc
                )

    async def _weekly_loop(self) -> None:
        """Schedule weekly maintenance; retain the existing weekday policy / 调度每周维护，沿用现有星期规则。"""
        while True:
            await asyncio.sleep(
                self.seconds_until(
                    "23:55",
                    weekday=self.config("weekly_day", 6),
                )
            )
            try:
                self.jobs.submit("weekly", self.weekly)
            except Exception as exc:
                self.logger.error(f"[seekmemory] weekly scheduling failed: {exc}")
                self.journal.record(
                    "scheduler", "failed", "weekly scheduling failed", error=exc
                )

    async def _idle_loop(self) -> None:
        """Observe capacity and runtime, then schedule eligible idle extraction / 观察容量和运行时，再调度符合条件的空闲抽取。"""
        while True:
            await asyncio.sleep(30)
            try:
                self.retry_writebacks()
                decision = self.capacity.observe()
                self.capacity.apply_maintenance(decision)
                await self.runtime_worker.tick()
                if self.should_flush():
                    self.jobs.submit("idle", lambda: self.flush("idle"))
            except Exception as exc:
                self.logger.error(f"[seekmemory] idle task failed: {exc}")
                self.journal.record(
                    "scheduler", "failed", "idle task submission failed", error=exc
                )

    async def _ingest_loop(self) -> None:
        """Schedule extraction only when its existing gates allow it / 仅在现有条件允许时调度抽取。"""
        while True:
            interval = max(120, int(self.config("ingest_interval_seconds", 600)))
            await asyncio.sleep(interval)
            try:
                self.retry_writebacks()
                if self.buffer is None or not self.buffer.items:
                    continue
                if not self.config("ingest_enabled", True):
                    continue
                if len(self.buffer.items) < int(self.config("ingest_min_pending", 20)):
                    continue
                cap = max(1, int(self.config("ingest_batch_topics", 20)))
                self.jobs.submit("ingest", lambda: self.flush("scheduled", limit=cap))
            except Exception as exc:
                self.logger.error(f"[seekmemory] ingest scheduling failed: {exc}")

    async def _dream_loop(self) -> None:
        """Schedule due catch-up and daily dream runs / 调度到期补跑及每日夜间整理。"""
        if self.dream is not None and self.dream.due():
            try:
                self.jobs.submit("dream", self.run_dream)
            except Exception as exc:
                self.logger.error(f"[seekmemory] dream catch-up failed: {exc}")
        while True:
            await asyncio.sleep(
                self.seconds_until(str(self.config("dream_time", "03:30")))
            )
            try:
                self.jobs.submit("dream", self.run_dream)
            except Exception as exc:
                self.logger.error(f"[seekmemory] dream scheduling failed: {exc}")
                self.journal.record(
                    "scheduler", "failed", "dream scheduling failed", error=exc
                )

    @staticmethod
    def seconds_until(hhmm: str, weekday: int | None = None) -> float:
        """Compute the next configured local schedule with the existing fallback / 按既有回退规则计算下一次本地调度时间。"""
        try:
            hour, minute = (int(value) for value in hhmm.split(":"))
            if not 0 <= hour <= 23 or not 0 <= minute <= 59:
                raise ValueError("invalid time")
        except Exception:
            hour, minute = 23, 50
        now = datetime.datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        if weekday is not None:
            weekday = int(weekday) % 7
            while target.weekday() != weekday:
                target += datetime.timedelta(days=1)
        return max((target - now).total_seconds(), 60)
