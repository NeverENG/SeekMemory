"""Periodic memory-maintenance scheduling."""

from __future__ import annotations

import asyncio
import datetime
from typing import Any, Callable


class BackgroundService:
    """Own the lifecycle and cadence of periodic memory work.

    The individual operations stay in IngestService, CapacityService,
    MaintenanceService and RuntimeWorker. This object only decides when they run.
    """

    def __init__(
        self,
        *,
        jobs,
        checkpoint,
        buffer,
        capacity,
        ingest,
        maintenance,
        import_service=None,
        dream,
        runtime_worker,
        journal,
        config: Callable[[str, Any], Any],
        logger,
    ) -> None:
        self.jobs = jobs
        self.checkpoint = checkpoint
        self.buffer = buffer
        self.capacity = capacity
        self.ingest = ingest
        self.maintenance = maintenance
        self.import_service = import_service
        self.dream = dream
        self.runtime_worker = runtime_worker
        self.journal = journal
        self.config = config
        self.logger = logger
        self._tasks: list[asyncio.Task] = []

    @property
    def tasks(self) -> list[asyncio.Task]:
        return self._tasks

    @property
    def dream_enabled(self) -> bool:
        return bool(self.dream is not None and self.dream.enabled)

    def start(self) -> bool:
        if self._tasks:
            return False
        operations = [
            self._weekly_loop,
            self._checkpoint_loop,
            self._dream_loop,
            self._import_cleanup_loop,
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
        tasks = self._tasks
        self._tasks = []
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

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
        decision = self.capacity.observe()
        return self.ingest.should_flush(
            capacity_state=decision.state,
            capacity_actions=decision.actions,
            dream_only=self.dream_enabled,
        )

    async def nightly(self) -> None:
        decision = self.capacity.observe()
        self.capacity.apply_maintenance(decision)
        await self.flush("nightly")

    async def weekly(self) -> dict:
        return await self.maintenance.weekly()

    async def dream_maintain(self) -> dict:
        return await self.weekly()

    async def run_dream(self) -> None:
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
        while True:
            interval = max(60, int(self.config("checkpoint_seconds", 1800)))
            await asyncio.sleep(interval)
            try:
                if self.checkpoint is not None:
                    self.checkpoint.flush()
            except Exception as exc:
                self.logger.error(f"[seekmemory] checkpoint failed: {exc}")

    async def _nightly_loop(self) -> None:
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
        while True:
            await asyncio.sleep(30)
            try:
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
        while True:
            interval = max(120, int(self.config("ingest_interval_seconds", 600)))
            await asyncio.sleep(interval)
            try:
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

    async def _import_cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(3600)
            try:
                if self.import_service is not None:
                    self.import_service.cleanup()
            except Exception as exc:
                self.journal.record(
                    "history_import", "warning", "import retention cleanup failed", error=exc
                )

    @staticmethod
    def seconds_until(hhmm: str, weekday: int | None = None) -> float:
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
