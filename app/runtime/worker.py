"""Poll and dispatch due work through injected callbacks; retry writes even when speaking is disabled.

通过注入回调轮询执行到期任务，关闭发言时仍补写。
"""

from __future__ import annotations

import asyncio
from typing import Callable

from .contracts import Clock, ProactiveDecision, ProactivePolicy, RunContext, RunResult, TraceSink
from .runtime import AgentRuntime
from .scheduler import Scheduler
from .topics import TopicCandidate, TopicSource


class RuntimeWorker:
    """Own polling, concurrency slots and in-process session deduplication; composition owns tasks and resources.

    管理轮询、并发名额及进程内会话去重，组装方管理任务及资源。
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
        clock: Clock | None = None,
        proactive_policy: ProactivePolicy | None = None,
        proactive_max_fanout: int = 5,
        topic_source: TopicSource | None = None,
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
        self.clock = clock
        self.proactive_policy = proactive_policy
        self.proactive_max_fanout = max(0, int(proactive_max_fanout))
        self.topic_source = topic_source
        self._dispatching: set[str] = set()
        self._semaphores: dict[object, asyncio.Semaphore] = {}

    def _record_failure(self, status: str, error: Exception, session_id: str = "") -> None:
        try:
            if self.trace is not None:
                self.trace.record("runtime", status, {"error": type(error).__name__, "session_id": session_id})
        except Exception:
            pass

    def retry_writebacks(self) -> int:
        """Retry only writes even when speaking is disabled / 即使关闭发言也只补写。"""
        retry = getattr(self.runtime, "retry_writebacks", None)
        if not callable(retry):
            return 0
        try:
            return int(retry())
        except Exception as exc:
            self._record_failure("writeback_retry_failed", exc)
            return 0

    def _moment(self, now: float | None) -> float:
        if now is not None:
            return float(now)
        if self.clock is None:
            raise RuntimeError("runtime worker requires now or an injected clock")
        return float(self.clock())

    def _semaphore(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        semaphore = self._semaphores.get(loop)
        if semaphore is None:
            semaphore = asyncio.Semaphore(self.max_concurrency)
            self._semaphores[loop] = semaphore
        return semaphore

    async def dispatch(self, session_id: str, now: float | None = None) -> RunResult | None:
        """Claim a concurrency slot, recheck due state and dispatch one session / 领取并发名额、复查到期状态并执行一个会话。"""
        if not self.enabled() or session_id in self._dispatching:
            return None
        moment = self._moment(now)
        self._dispatching.add(session_id)
        try:
            async with self._semaphore():
                if not self.enabled():
                    return None
                # Recheck time and due state after waiting for a slot.
                # 等待并发名额后复查时间及到期状态。
                if self.clock is not None:
                    moment = max(moment, self._moment(None))
                if not self.scheduler.due([session_id], moment):
                    return None
                return await self.runtime.dispatch_deferred(
                    self.run_context(session_id, moment),
                    now=moment,
                    max_attempts=max(1, int(self.max_attempts())),
                    base_seconds=max(0.1, float(self.base_seconds())),
                )
        finally:
            self._dispatching.discard(session_id)

    def _topic_for(self, session_id: str, now: float) -> TopicCandidate | None:
        if self.topic_source is None:
            return None
        try:
            candidates = self.topic_source.candidates(
                session_id, now=now, limit=1
            )
        except Exception as exc:  # noqa: BLE001 - topic failure skips proactive / 话题失败跳过主动发言
            self._record_failure("proactive_topic_failed", exc, session_id)
            return None
        return candidates[0] if candidates else None

    async def dispatch_proactive(
        self,
        session_id: str,
        decision: ProactiveDecision,
        now: float | None = None,
        topic: TopicCandidate | None = None,
    ) -> RunResult | None:
        """Use the same concurrency and session guard for proactive work / 主动任务复用相同并发及会话保护。"""
        if not self.enabled() or session_id in self._dispatching:
            return None
        moment = self._moment(now)
        self._dispatching.add(session_id)
        try:
            async with self._semaphore():
                if not self.enabled():
                    return None
                return await self.runtime.dispatch_proactive(
                    self.run_context(session_id, moment),
                    decision,
                    topic=topic,
                    now=moment,
                )
        finally:
            self._dispatching.discard(session_id)

    async def tick(self, now: float | None = None) -> int:
        """Retry writes first, then select enabled due work; return dispatched count / 先补写，再选择已启用的到期任务，返回执行数量。"""
        self.retry_writebacks()
        if not self.enabled():
            return 0
        moment = self._moment(now)
        try:
            due = self.scheduler.due(self.session_ids(100), moment)
        except Exception as exc:  # noqa: BLE001 - scheduler failure is fail-open
            self._record_failure("scheduler_failed", exc)
            return 0
        dispatched = 0
        if due:
            async def run_one(item) -> bool:
                """Isolate one dispatch failure while other sessions continue / 隔离一次执行失败，其他会话继续。"""
                try:
                    result = await self.dispatch(item.session_id, moment)
                except Exception as exc:  # noqa: BLE001 - isolate failed runs / 隔离失败运行
                    self._record_failure("dispatch_failed", exc, item.session_id)
                    return False
                return result is not None

            results = await asyncio.gather(*(run_one(item) for item in due))
            dispatched = sum(1 for result in results if result)
        if self.proactive_policy is None:
            return dispatched
        try:
            plan = self.scheduler.proactive_due(
                self.session_ids(100),
                moment,
                self.proactive_policy,
                max_fanout=self.proactive_max_fanout,
            )
        except Exception as exc:  # noqa: BLE001 - isolate proactive failure / 隔离主动计划失败
            self._record_failure("proactive_plan_failed", exc)
            return dispatched
        deferred_ids = {item.session_id for item in due}
        for candidate in plan.selected:
            if candidate.session_id in deferred_ids:
                continue
            topic = self._topic_for(candidate.session_id, moment)
            if self.topic_source is not None and topic is None:
                self._record_failure(
                    "proactive_no_topic", RuntimeError("no_topic"),
                    candidate.session_id,
                )
                clear = getattr(self.runtime, "clear_proactive", None)
                if callable(clear):
                    clear(candidate.session_id)
                continue
            try:
                result = await self.dispatch_proactive(
                    candidate.session_id, candidate.decision, moment, topic
                )
            except Exception as exc:  # noqa: BLE001 - isolate failed runs / 隔离失败运行
                self._record_failure(
                    "proactive_dispatch_failed", exc, candidate.session_id
                )
                continue
            if result is not None:
                dispatched += 1
        return dispatched

    async def run_forever(self) -> None:
        """Poll existing work; retry writes once more on cancellation / 轮询已有任务，取消时再补写一次。"""
        try:
            while True:
                await asyncio.sleep(max(1.0, float(self.interval_seconds())))
                try:
                    await self.tick()
                except Exception as exc:  # noqa: BLE001 - keep polling / 继续轮询
                    self._record_failure("worker_tick_failed", exc)
        finally:
            self.retry_writebacks()
