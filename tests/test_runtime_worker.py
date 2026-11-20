"""One worker concurrency boundary for queued, direct and scanned dispatch."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime import (  # noqa: E402
    AgentRuntime, DefaultProactivePolicy, InMemoryStateStore, RunContext, RunRecorder,
    RuntimeInput, RuntimeWorker, Scheduler, SessionState, TaskPriority, TaskStatus, TopicCandidate,
)


class WorkerTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.now = 100.0
        self.enabled = True
        self.active = 0
        self.max_active = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.sessions = []
        self.context_times = []
        self.store = InMemoryStateStore()
        for session in ("s1", "s2", "s3"):
            self.store.put(SessionState(session, wait_until=100))
        self.runtime = AgentRuntime(
            self.store, clock=lambda: self.now,
            recorder=RunRecorder(sources=None, buffer=None, checkpoint=None, episodes=None),
            model_gateway=SimpleNamespace(complete=self.complete),
            message_sender=SimpleNamespace(send=self.send),
        )
        self.worker = RuntimeWorker(
            runtime=self.runtime, scheduler=Scheduler(self.store),
            enabled=lambda: self.enabled, session_ids=lambda limit: ["s2", "s3"],
            run_context=self.context, interval_seconds=lambda: 1,
            max_attempts=lambda: 3, base_seconds=lambda: 2, max_concurrency=1,
            clock=lambda: self.now,
        )

    def context(self, session_id: str, now: float) -> RunContext:
        self.context_times.append(now)
        return RunContext(session_id, "hello", source_id="u1")

    async def complete(self, session_id: str, *args) -> str:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.sessions.append(session_id)
        self.started.set()
        try:
            await self.release.wait()
            return "reply"
        finally:
            self.active -= 1

    async def send(self, *args) -> bool:
        return True

    async def first_dispatch(self):
        task = asyncio.create_task(self.worker.dispatch("s1", 100))
        await asyncio.wait_for(self.started.wait(), timeout=1)
        return task

    def use_foreground(self) -> None:
        self.worker = RuntimeWorker(
            runtime=self.runtime, scheduler=Scheduler(self.store),
            enabled=lambda: self.enabled, session_ids=lambda limit: ["s1", "s2"],
            run_context=self.context, interval_seconds=lambda: 1,
            max_attempts=lambda: 3, base_seconds=lambda: 2,
            max_concurrency=2, clock=lambda: self.now,
            foreground=self.runtime.foreground,
        )

    def use_guarded_foreground(self) -> None:
        self.runtime = AgentRuntime(
            self.store, clock=lambda: self.now,
            recorder=RunRecorder(sources=None, buffer=None, checkpoint=None, episodes=None),
            model_gateway=SimpleNamespace(complete=self.complete),
            message_sender=SimpleNamespace(send=self.send), run_control_enabled=True,
        )
        self.use_foreground()

    async def test_guarded_foreground_yields_after_model_before_send(self) -> None:
        self.use_guarded_foreground()
        first = await self.first_dispatch()
        background = self.runtime.foreground.current()
        interactive = self.runtime.foreground.submit("conversation", "other-lane", TaskPriority.INTERACTIVE)
        self.assertEqual(self.runtime.foreground.current().status, TaskStatus.YIELD_REQUESTED)
        self.assertIsNone(self.runtime.foreground.claim_next())

        self.release.set()
        admitted = await asyncio.wait_for(self.runtime.foreground.claim_when_ready(interactive.task_id), 1)
        self.assertEqual(admitted.task_id, interactive.task_id)
        self.assertEqual(self.runtime.foreground.view(background.task_id).status, TaskStatus.READY)
        self.assertFalse(first.done())
        self.assertTrue(self.runtime.foreground.finish(interactive.task_id))
        self.assertTrue((await asyncio.wait_for(first, 1)).delivered)
        self.assertIsNone(self.runtime.foreground.current())

    async def test_superseded_guarded_foreground_does_not_send_after_yield(self) -> None:
        self.use_guarded_foreground()
        first = await self.first_dispatch()
        handle = self.runtime.current_run("s1")
        interactive = self.runtime.foreground.submit("conversation", "other-lane", TaskPriority.INTERACTIVE)
        self.release.set()
        await asyncio.wait_for(self.runtime.foreground.claim_when_ready(interactive.task_id), 1)
        self.assertTrue(self.runtime.supersede_run("s1", handle.run_id))
        self.assertTrue(self.runtime.foreground.finish(interactive.task_id))
        self.assertEqual((await asyncio.wait_for(first, 1)).error, "superseded")
        self.assertIsNone(self.runtime.foreground.current())
        self.assertIsNone(self.runtime.foreground.claim_next())

    async def test_cancelled_guarded_foreground_waiter_cleans_up_without_releasing_other_task(self) -> None:
        self.use_guarded_foreground()
        first = await self.first_dispatch()
        interactive = self.runtime.foreground.submit("conversation", "other-lane", TaskPriority.INTERACTIVE)
        self.release.set()
        await asyncio.wait_for(self.runtime.foreground.claim_when_ready(interactive.task_id), 1)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.assertEqual(self.runtime.foreground.current().task_id, interactive.task_id)
        self.assertTrue(self.runtime.foreground.finish(interactive.task_id))
        self.assertIsNone(self.runtime.foreground.claim_next())

    async def test_unguarded_foreground_does_not_claim_a_safe_point(self) -> None:
        self.use_foreground()
        first = await self.first_dispatch()
        interactive = self.runtime.foreground.submit("conversation", "other-lane", TaskPriority.INTERACTIVE)
        self.release.set()
        self.assertTrue((await asyncio.wait_for(first, 1)).delivered)
        self.assertEqual(self.runtime.foreground.claim_next().task_id, interactive.task_id)

    async def test_guarded_proactive_yields_before_sending(self) -> None:
        self.use_guarded_foreground()
        policy = DefaultProactivePolicy(enabled=True)
        self.worker.proactive_policy = policy
        state = self.store.get("s1")
        state.wait_until = 0
        state.proactive_due_at = 100
        self.store.put(state)
        decision = self.worker.scheduler.proactive_due(["s1"], 100, policy).selected[0].decision
        proactive = asyncio.create_task(self.worker.dispatch_proactive("s1", decision, now=100))
        await asyncio.wait_for(self.started.wait(), 1)
        interactive = self.runtime.foreground.submit("conversation", "other-lane", TaskPriority.INTERACTIVE)
        self.release.set()
        await asyncio.wait_for(self.runtime.foreground.claim_when_ready(interactive.task_id), 1)
        self.assertFalse(proactive.done())
        self.assertTrue(self.runtime.foreground.finish(interactive.task_id))
        self.assertTrue((await asyncio.wait_for(proactive, 1)).delivered)
        self.assertIsNone(self.runtime.foreground.current())

    async def test_started_send_keeps_foreground_until_its_real_result(self) -> None:
        self.use_guarded_foreground()
        send_started = asyncio.Event()
        send_release = asyncio.Event()

        async def slow_send(*args) -> bool:
            send_started.set()
            await send_release.wait()
            return True

        self.runtime.message_sender = SimpleNamespace(send=slow_send)
        first = await self.first_dispatch()
        self.release.set()
        await asyncio.wait_for(send_started.wait(), 1)
        interactive = self.runtime.foreground.submit("conversation", "other-lane", TaskPriority.INTERACTIVE)
        self.assertEqual(self.runtime.foreground.current().status, TaskStatus.YIELD_REQUESTED)
        self.assertIsNone(self.runtime.foreground.claim_next())
        send_release.set()
        self.assertTrue((await asyncio.wait_for(first, 1)).delivered)
        self.assertEqual(self.runtime.foreground.claim_next().task_id, interactive.task_id)

    async def test_opt_in_worker_serializes_real_deferred_dispatches(self) -> None:
        self.use_foreground()
        first = await self.first_dispatch()
        second = asyncio.create_task(self.worker.dispatch("s2", 100))
        await asyncio.sleep(0)
        self.assertEqual(self.sessions, ["s1"])
        self.assertEqual(self.store.get("s2").dispatch_attempts, 0)
        self.release.set()
        a, b = await asyncio.gather(first, second)
        self.assertTrue(a.delivered)
        self.assertTrue(b.delivered)
        self.assertEqual(self.sessions, ["s1", "s2"])
        self.assertIsNone(self.runtime.foreground.current())
        self.assertIsNone(self.runtime.foreground.claim_next())

    async def test_cancelled_queued_foreground_work_leaves_due_input_retryable(self) -> None:
        self.use_foreground()
        first = await self.first_dispatch()
        queued = asyncio.create_task(self.worker.dispatch("s2", 100))
        await asyncio.sleep(0)
        queued.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await queued
        self.assertEqual(self.store.get("s2").dispatch_attempts, 0)
        self.release.set()
        await first
        self.assertIsNone(self.runtime.foreground.claim_next())
        self.assertTrue((await self.worker.dispatch("s2", 100)).delivered)

    async def test_foreground_waiter_rechecks_due_state_after_new_input(self) -> None:
        self.use_foreground()
        first = await self.first_dispatch()
        queued = asyncio.create_task(self.worker.dispatch("s2", 100))
        await asyncio.sleep(0)
        self.store.get("s2").wait_until = 200
        self.release.set()
        await first
        self.assertIsNone(await queued)
        self.assertEqual(self.sessions, ["s1"])
        self.assertEqual(self.store.get("s2").dispatch_attempts, 0)
        self.assertIsNone(self.runtime.foreground.claim_next())

    async def test_foreground_waiter_rechecks_disabled_gate(self) -> None:
        self.use_foreground()
        first = await self.first_dispatch()
        queued = asyncio.create_task(self.worker.dispatch("s2", 100))
        await asyncio.sleep(0)
        self.enabled = False
        self.release.set()
        await first
        self.assertIsNone(await queued)
        self.assertEqual(self.store.get("s2").dispatch_attempts, 0)
        self.assertIsNone(self.runtime.foreground.claim_next())

    async def test_cancelling_started_foreground_run_releases_slot_for_other_lane(self) -> None:
        self.use_foreground()
        first = await self.first_dispatch()
        queued = asyncio.create_task(self.worker.dispatch("s2", 100))
        await asyncio.sleep(0)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.release.set()
        self.assertTrue((await asyncio.wait_for(queued, timeout=1)).delivered)
        self.assertIsNone(self.runtime.foreground.current())

    async def test_failed_foreground_dispatch_releases_slot_and_can_retry(self) -> None:
        self.use_foreground()
        original_context = self.worker.run_context

        def fail_context(session_id: str, now: float) -> RunContext:
            raise ValueError("context unavailable")

        self.worker.run_context = fail_context
        with self.assertRaisesRegex(ValueError, "context unavailable"):
            await self.worker.dispatch("s1", 100)
        self.assertIsNone(self.runtime.foreground.current())
        self.assertIsNone(self.runtime.foreground.claim_next())
        self.worker.run_context = original_context
        self.release.set()
        self.assertTrue((await self.worker.dispatch("s1", 100)).delivered)

    async def test_proactive_and_deferred_share_the_same_foreground(self) -> None:
        self.use_foreground()
        policy = DefaultProactivePolicy(enabled=True)
        self.worker.proactive_policy = policy
        state = self.store.get("s2")
        state.wait_until = 0
        state.proactive_due_at = 100
        self.store.put(state)
        decision = self.worker.scheduler.proactive_due(["s2"], 100, policy).selected[0].decision
        first = await self.first_dispatch()
        proactive = asyncio.create_task(self.worker.dispatch_proactive("s2", decision, now=100))
        await asyncio.sleep(0)
        self.assertEqual(self.sessions, ["s1"])
        self.release.set()
        await first
        self.assertTrue((await proactive).delivered)
        self.assertEqual(self.sessions, ["s1", "s2"])
        self.assertIsNone(self.runtime.foreground.current())

    async def test_tick_failure_diagnostics_exclude_session_and_exception_body(self) -> None:
        sensitive_session = "private-session-8675309"
        sensitive_message = "secret-message-from-user"
        self.store.put(SessionState(sensitive_session, wait_until=100))
        self.worker.session_ids = lambda limit: [sensitive_session, "s3"]
        records = []
        self.worker.trace = SimpleNamespace(
            record=lambda kind, status, context: records.append((kind, status, context))
        )
        self.release.set()

        def context(session_id: str, now: float) -> RunContext:
            if session_id == sensitive_session:
                raise ValueError(sensitive_message)
            return self.context(session_id, now)

        self.worker.run_context = context
        self.assertEqual(await self.worker.tick(now=100), 1)
        self.assertEqual(self.sessions, ["s3"])
        self.assertEqual(records, [("runtime", "dispatch_failed", {"error": "ValueError"})])
        self.assertNotIn(sensitive_session, repr(records))
        self.assertNotIn(sensitive_message, repr(records))

    async def test_direct_calls_and_ticks_share_one_concurrency_limit(self) -> None:
        first = await self.first_dispatch()
        direct = asyncio.create_task(self.worker.dispatch("s2", 100))
        tick = asyncio.create_task(self.worker.tick(now=100))
        await asyncio.sleep(0)
        peak_while_blocked = self.max_active
        self.release.set()
        await asyncio.gather(first, direct, tick)
        self.assertEqual(peak_while_blocked, 1)
        self.assertEqual(self.max_active, 1)
        self.assertEqual(sorted(self.sessions), ["s1", "s2", "s3"])

    async def test_topic_source_error_keeps_due_proactive_for_retry(self) -> None:
        state = self.store.get("s2")
        state.wait_until = 0.0
        state.proactive_due_at = 100.0
        self.store.put(state)
        self.worker.session_ids = lambda limit: ["s2"]
        self.worker.proactive_policy = DefaultProactivePolicy(enabled=True)
        queries = []

        def candidates(session_id: str, *, now: float, limit: int):
            queries.append(session_id)
            if len(queries) == 1:
                raise OSError("sensitive topic backend failure")
            return [TopicCandidate("a relevant topic")]

        self.worker.topic_source = SimpleNamespace(candidates=candidates)
        records = []
        self.worker.trace = SimpleNamespace(
            record=lambda kind, status, context: records.append((kind, status, context))
        )
        self.release.set()

        self.assertEqual(await self.worker.tick(now=100), 0)
        self.assertEqual(self.store.get("s2").proactive_due_at, 100.0)
        self.assertEqual(self.sessions, [])
        self.assertEqual(records, [("runtime", "proactive_topic_failed", {"error": "OSError"})])
        self.assertEqual(await self.worker.tick(now=100), 1)
        self.assertEqual(self.sessions, ["s2"])
        self.assertEqual(self.store.get("s2").proactive_due_at, 0.0)
        self.assertEqual(queries, ["s2", "s2"])

    async def test_queued_proactive_rechecks_due_after_new_input_reschedules_it(self) -> None:
        policy = DefaultProactivePolicy(enabled=True)
        self.worker.proactive_policy = policy
        state = self.store.get("s2")
        state.proactive_due_at = 100.0
        self.store.put(state)
        selected = self.worker.scheduler.proactive_due(["s2"], 100, policy).selected[0]

        first = await self.first_dispatch()  # Hold the only worker slot.
        queued = asyncio.create_task(
            self.worker.dispatch_proactive("s2", selected.decision, now=100)
        )
        await asyncio.sleep(0)
        self.now = 101.0
        self.runtime.accept_user(RuntimeInput(
            "s2", "new message", event_time=self.now, speaker_id="user",
        ), now=self.now)
        self.runtime.schedule_proactive("s2", 99, now=self.now)
        self.release.set()
        await first
        self.assertIsNone(await queued)
        self.assertEqual(self.sessions, ["s1"])
        self.assertEqual(self.store.get("s2").proactive_due_at, 200.0)

    async def test_queued_proactive_uses_fresh_time_when_still_due(self) -> None:
        policy = DefaultProactivePolicy(enabled=True)
        self.worker.proactive_policy = policy
        state = self.store.get("s2")
        state.proactive_due_at = 100.0
        self.store.put(state)
        selected = self.worker.scheduler.proactive_due(["s2"], 100, policy).selected[0]

        first = await self.first_dispatch()
        queued = asyncio.create_task(
            self.worker.dispatch_proactive("s2", selected.decision, now=100)
        )
        await asyncio.sleep(0)
        self.now = 120.0
        self.release.set()
        await first
        self.assertTrue((await queued).delivered)
        self.assertEqual(self.context_times, [100, 120])
        self.assertEqual(self.sessions, ["s1", "s2"])

    async def test_duplicate_session_is_rejected_while_queued(self) -> None:
        first = await self.first_dispatch()
        queued = asyncio.create_task(self.worker.dispatch("s2", 100))
        await asyncio.sleep(0)
        duplicate = await self.worker.dispatch("s2", 100)
        self.release.set()
        await asyncio.gather(first, queued)
        self.assertIsNone(duplicate)
        self.assertEqual(self.sessions.count("s2"), 1)

    async def test_cancelled_queued_call_releases_session_for_later_dispatch(self) -> None:
        first = await self.first_dispatch()
        queued = asyncio.create_task(self.worker.dispatch("s2", 100))
        await asyncio.sleep(0)
        queued.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await queued
        attempts_before_retry = self.store.get("s2").dispatch_attempts
        self.release.set()
        await first
        result = await self.worker.dispatch("s2", 100)
        self.assertEqual(attempts_before_retry, 0)
        self.assertTrue(result.delivered)

    async def test_queued_dispatch_rechecks_gate_after_acquiring_slot(self) -> None:
        first = await self.first_dispatch()
        queued = asyncio.create_task(self.worker.dispatch("s2", 100))
        await asyncio.sleep(0)
        self.enabled = False
        self.release.set()
        await first
        self.assertIsNone(await queued)
        self.assertEqual(self.sessions, ["s1"])

    async def test_queued_dispatch_rechecks_changed_deadline(self) -> None:
        first = await self.first_dispatch()
        queued = asyncio.create_task(self.worker.dispatch("s2", 100))
        await asyncio.sleep(0)
        self.store.get("s2").wait_until = 200
        self.release.set()
        await first
        self.assertIsNone(await queued)
        self.assertEqual(self.sessions, ["s1"])

    async def test_queued_context_uses_fresh_clock_at_acquired_slot(self) -> None:
        first = await self.first_dispatch()
        queued = asyncio.create_task(self.worker.dispatch("s2", 100))
        await asyncio.sleep(0)
        self.now = 160
        self.release.set()
        await asyncio.gather(first, queued)
        self.assertEqual(self.context_times, [100, 160])

    async def test_cancelled_active_call_releases_worker_slot(self) -> None:
        first = await self.first_dispatch()
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.release.set()
        self.assertTrue((await self.worker.dispatch("s2", 100)).delivered)
        self.now = 102
        self.assertTrue((await self.worker.dispatch("s1", 102)).delivered)


if __name__ == "__main__":
    unittest.main()
