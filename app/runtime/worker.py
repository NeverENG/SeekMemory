"""Background dispatch loop for due runtime sessions."""

from __future__ import annotations

import asyncio
import time
from typing import Callable

from .contracts import RunContext, RunResult
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
    ) -> None:
        self.runtime = runtime
        self.scheduler = scheduler
        self.enabled = enabled
        self.session_ids = session_ids
        self.run_context = run_context
        self.interval_seconds = interval_seconds
        self.max_attempts = max_attempts
        self.base_seconds = base_seconds
        self._lock = asyncio.Lock()
        self._dispatching: set[str] = set()

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
        dispatched = 0
        async with self._lock:
            moment = time.time() if now is None else float(now)
            due = self.scheduler.due(self.session_ids(100), moment)
            for item in due:
                try:
                    if await self.dispatch(item.session_id, moment) is not None:
                        dispatched += 1
                except Exception:
                    continue
        return dispatched

    async def run_forever(self) -> None:
        while True:
            await asyncio.sleep(max(1.0, float(self.interval_seconds())))
            try:
                await self.tick()
            except Exception:
                continue
