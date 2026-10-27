"""Background dispatch loop for due runtime sessions."""

from __future__ import annotations

import asyncio
import time
from typing import Callable

from .contracts import RunContext, RunResult, TraceSink
from .runtime import AgentRuntime
from .scheduler import Scheduler


class RuntimeWorker:
    """Own due-session dispatch and its in-flight dedupe set.

    The worker does not know the host or the database. The composition layer
    provides session ids and maps each id to a RunContext.
    """

    def __init__(
        self,
        *,
        runtime: AgentRuntime,
        scheduler: Scheduler,
        enabled: Callable[[], bool],
        session_ids: Callable[[int], list[str]],
        run_context: Callable[[str, float], RunContext],
        interval_seconds: Callable[[], float],
        max_attempts: Callable[[], int],
        base_seconds: Callable[[], float],
        trace: TraceSink | None = None,
        max_concurrency: int = 4,
    ) -> None:
        self.runtime = runtime
        self.scheduler = scheduler
        self.enabled = enabled
        self.session_ids = session_ids
        self.run_context = run_context
        self.interval_seconds = interval_seconds
        self.max_attempts = max_attempts
        self.base_seconds = base_seconds
        self.trace = trace
        self.max_concurrency = max(1, int(max_concurrency))
        self._dispatching: set[str] = set()

    def _record_failure(self, status: str, error: Exception, session_id: str = "") -> None:
        if self.trace is not None:
            self.trace.record(
                "runtime",
                status,
                {
                    "session_id": session_id,
                    "error": type(error).__name__,
                },
            )

    async def dispatch(self, session_id: str, now: float | None = None) -> RunResult | None:
        if not self.enabled() or session_id in self._dispatching:
            return None
        self._dispatching.add(session_id)
        try:
            moment = time.time() if now is None else float(now)
            return await self.runtime.dispatch_deferred(
                self.run_context(session_id, moment),
                now=moment,
                max_attempts=max(1, int(self.max_attempts())),
                base_seconds=max(0.1, float(self.base_seconds())),
            )
        finally:
            self._dispatching.discard(session_id)

    async def tick(self, now: float | None = None) -> int:
        if not self.enabled():
            return 0
        moment = time.time() if now is None else float(now)
        try:
            due = self.scheduler.due(self.session_ids(100), moment)
        except Exception as exc:  # noqa: BLE001 - scheduler failure is fail-open
            self._record_failure("scheduler_failed", exc)
            return 0
        if not due:
            return 0
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def run_one(item) -> bool:
            async with semaphore:
                try:
                    result = await self.dispatch(item.session_id, moment)
                except Exception as exc:  # noqa: BLE001 - one run must not stop the tick
                    self._record_failure("dispatch_failed", exc, item.session_id)
                    return False
                return result is not None

        results = await asyncio.gather(*(run_one(item) for item in due))
        return sum(1 for result in results if result)

    async def run_forever(self) -> None:
        while True:
            await asyncio.sleep(max(1.0, float(self.interval_seconds())))
            try:
                await self.tick()
            except Exception as exc:  # noqa: BLE001 - keep the worker alive
                self._record_failure("worker_tick_failed", exc)
