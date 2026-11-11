"""Caller-visible supersession on opt-in runtime-owned background dispatch."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime import (AgentRuntime, InMemoryStateStore, RunContext,
                         RunRecorder, RuntimeInput, ProactiveDecision)
from app.runtime.contracts import RunKind, RunTrigger
from app.runtime.actions import ActionExecutor, ActionLedger
from app.runtime.contracts import ActionResult, ActionStatus, MemoryContext
from store import open_store


class RuntimeDispatchSupersessionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = open_store(":memory:")
        self.store = InMemoryStateStore()
        self.episodes, self.sent, self.actions = [], [], []
        self.now = 100.0
        self.model_started = asyncio.Event()
        self.model_release = asyncio.Event()
        self.model = SimpleNamespace(complete=self.complete)
        self.recorder = RunRecorder(
            sources=self.db.sources, buffer=None, checkpoint=None,
            episodes=SimpleNamespace(record=self.episodes.append),
        )
        self.runtime = AgentRuntime(
            self.store, clock=lambda: self.now, wait_seconds=5,
            recorder=self.recorder, model_gateway=self.model,
            message_sender=SimpleNamespace(send=self.send), run_control_enabled=True,
        )

    async def asyncTearDown(self):
        self.db.close()

    async def complete(self, *_):
        self.model_started.set()
        await self.model_release.wait()
        return "obsolete reply"

    async def send(self, session_id, text):
        self.sent.append((session_id, text))
        return True

    def accept(self, event_id, *, lane="s1", private=False):
        return self.runtime.accept_user(RuntimeInput(
            lane, event_id, event_id=event_id, speaker_id="person",
            private=private, event_time=self.now,
        ), now=self.now)

    async def test_deferred_new_input_during_model_keeps_newer_wait_and_no_old_retry(self):
        self.accept("old")
        self.now = 105.0
        old = asyncio.create_task(self.runtime.dispatch_deferred(
            RunContext("s1", "old", source_id="old"), now=105.0,
        ))
        await asyncio.wait_for(self.model_started.wait(), 1)
        self.now = 106.0
        newer = self.accept("new")
        self.assertTrue(newer.source_id)
        self.model_release.set()
        result = await old
        self.assertFalse(result.delivered)
        self.assertEqual(result.error, "superseded")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.episodes, [])
        self.assertEqual(self.store.get("s1").wait_until, 111.0)
        self.assertEqual(self.store.get("s1").next_retry_at, 0.0)
        self.assertEqual(self.store.get("s1").unread_count, 2)
        self.assertEqual(len(self.db.sources.recent_sources(since="", limit=10)), 2)

    async def test_disabled_admission_does_not_treat_provider_error_as_supersession(self):
        from app.runtime.runs import RunSupersededError

        async def fail(*_):
            raise RunSupersededError("provider_error")

        self.runtime = AgentRuntime(
            self.store, clock=lambda: self.now, wait_seconds=5,
            recorder=self.recorder, model_gateway=SimpleNamespace(complete=fail),
            message_sender=SimpleNamespace(send=self.send),
        )
        self.runtime.observe(RuntimeInput("s1", "old", event_time=self.now), now=self.now)
        self.now = 105.0
        result = await self.runtime.dispatch_deferred(
            RunContext("s1", "old", source_id="old"), now=self.now,
        )
        self.assertEqual(result.error, "RunSupersededError")
        self.assertEqual(self.store.get("s1").next_retry_at, 107.0)
        self.assertEqual(len(self.episodes), 1)

    async def test_deferred_busy_lane_leaves_due_work_for_later(self):
        self.accept("old")
        self.now = 105.0
        first = asyncio.create_task(self.runtime.dispatch_deferred(
            RunContext("s1", "old", source_id="old"), now=self.now,
        ))
        await asyncio.wait_for(self.model_started.wait(), 1)
        second = await self.runtime.dispatch_deferred(
            RunContext("s1", "old", source_id="old"), now=self.now,
        )
        self.assertEqual(second.error, "run_busy")
        self.assertEqual(self.store.get("s1").dispatch_attempts, 1)
        self.assertEqual(self.store.get("s1").wait_until, 105.0)
        self.assertEqual(self.sent, [])
        self.model_release.set()
        self.assertTrue((await first).delivered)
        self.assertEqual(len(self.sent), 1)

    async def test_new_input_after_supersession_dispatches_when_due(self):
        self.accept("old")
        self.now = 105.0
        old = asyncio.create_task(self.runtime.dispatch_deferred(
            RunContext("s1", "old", source_id="old"), now=self.now,
        ))
        await asyncio.wait_for(self.model_started.wait(), 1)
        self.now = 106.0
        newer = self.accept("new")
        self.model_release.set()
        self.assertEqual((await old).error, "superseded")
        self.assertEqual(self.sent, [])
        self.now = 111.0
        delivered = await self.runtime.dispatch_deferred(
            RunContext("s1", "new", source_id=newer.source_id), now=self.now,
        )
        self.assertTrue(delivered.delivered)
        self.assertEqual(self.sent, [("s1", "obsolete reply")])
        self.assertEqual(self.store.get("s1").next_retry_at, 0.0)
        sources = self.db.sources.recent_sources(since="", limit=10)
        reply = next(row for row in sources if row.role == "assistant")
        self.assertEqual(reply.reply_to, newer.source_id)

    async def test_deferred_finishing_old_run_does_not_remove_new_user_run(self):
        self.accept("old")
        self.now = 105.0
        old = asyncio.create_task(self.runtime.dispatch_deferred(
            RunContext("s1", "old", source_id="old"), now=105.0,
        ))
        await asyncio.wait_for(self.model_started.wait(), 1)
        self.now = 106.0
        event = RuntimeInput("s1", "new", event_id="new", speaker_id="person",
                             private=True, event_time=self.now)
        receipt = self.runtime.accept_user(event, now=self.now)
        newer = self.runtime.begin_run("s1", RunTrigger(RunKind.USER, event, self.now), receipt=receipt)
        self.assertIsNotNone(newer)
        self.model_release.set()
        self.assertEqual((await old).error, "superseded")
        self.assertIs(self.runtime.current_run("s1"), newer)
        self.assertEqual(self.sent, [])

    async def test_proactive_due_during_user_run_is_not_consumed(self):
        self.accept("old")
        self.runtime.schedule_proactive("s1", 0.0, now=self.now)
        event = RuntimeInput("s1", "direct", event_id="direct", speaker_id="person",
                             private=True, event_time=self.now)
        receipt = self.runtime.accept_user(event, now=self.now)
        user = self.runtime.begin_run("s1", RunTrigger(RunKind.USER, event, self.now), receipt=receipt)
        self.model_release.set()  # Old behavior must fail, not hang in the fake provider.
        result = await self.runtime.dispatch_proactive(
            RunContext("s1", "topic"), ProactiveDecision(True, "due"), now=self.now,
        )
        self.assertFalse(result.delivered)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.store.get("s1").proactive_due_at, self.now)
        self.assertIs(self.runtime.current_run("s1"), user)

    async def test_proactive_model_return_after_new_input_does_not_send_or_record_error(self):
        self.accept("old")
        self.runtime.schedule_proactive("s1", 5.0, now=self.now)
        self.now = 105.0
        old = asyncio.create_task(self.runtime.dispatch_proactive(
            RunContext("s1", "topic"), ProactiveDecision(True, "due"), now=self.now,
        ))
        await asyncio.wait_for(self.model_started.wait(), 1)
        self.now = 106.0
        self.accept("new")
        self.model_release.set()
        result = await old
        self.assertFalse(result.delivered)
        self.assertEqual(result.error, "superseded")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.episodes, [])
        self.assertEqual(self.store.get("s1").proactive_attempts, 0)

    async def test_new_input_before_model_request_skips_model_and_send(self):
        self.accept("old")
        self.now = 105.0

        def context(_):
            self.now = 106.0
            self.accept("new")
            return MemoryContext(text="memory")

        self.runtime.memory_context = SimpleNamespace(build_context=context)
        result = await self.runtime.dispatch_deferred(RunContext("s1", "old", source_id="old"), now=105.0)
        self.assertEqual(result.error, "superseded")
        self.assertFalse(self.model_started.is_set())
        self.assertEqual(self.sent, [])
        self.assertEqual(self.episodes, [])
        self.assertEqual(self.store.get("s1").wait_until, 111.0)

    async def test_new_input_during_context_recording_skips_model_call(self):
        self.accept("old")
        self.now = 105.0

        def record(_):
            self.now = 106.0
            self.accept("new")

        self.runtime.context_recorder = SimpleNamespace(record_context_injection=record)
        result = await self.runtime.dispatch_deferred(RunContext("s1", "old", source_id="old"), now=105.0)
        self.assertEqual(result.error, "superseded")
        self.assertFalse(self.model_started.is_set())
        self.assertEqual(self.sent, [])
        self.assertEqual(self.episodes, [])

    async def test_model_failure_after_supersession_is_not_retried_as_old_reply(self):
        self.accept("old")
        self.now = 105.0

        async def failed(*_):
            self.now = 106.0
            self.accept("new")
            raise RuntimeError("provider unavailable")

        self.model.complete = failed
        result = await self.runtime.dispatch_deferred(RunContext("s1", "old", source_id="old"), now=105.0)
        self.assertEqual(result.error, "superseded")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.episodes, [])
        self.assertEqual(self.store.get("s1").next_retry_at, 0.0)

    async def test_host_abort_after_supersession_propagates_without_old_retry(self):
        self.accept("old")
        self.now = 105.0
        task = asyncio.create_task(self.runtime.dispatch_deferred(
            RunContext("s1", "old", source_id="old"), now=105.0,
        ))
        await asyncio.wait_for(self.model_started.wait(), 1)
        self.now = 106.0
        self.accept("new")
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.store.get("s1").next_retry_at, 0.0)
        self.assertEqual(self.episodes, [])
        self.assertEqual(self.sent, [])

    async def test_started_host_action_success_is_not_falsely_cancelled(self):
        self.accept("old")
        self.now = 105.0
        self.model_release.set()
        sink = SimpleNamespace(append=self.actions.append)

        async def send_and_accept(request):
            self.now = 106.0
            self.accept("new")
            return await self.action_send(request)

        self.runtime.message_sender = None
        self.runtime.action_executor = ActionExecutor(
            SimpleNamespace(execute=send_and_accept), ActionLedger(sink), clock=lambda: self.now,
        )
        result = await self.runtime.dispatch_deferred(
            RunContext("s1", "old", source_id="old"), now=105.0,
        )
        self.assertTrue(result.delivered)
        self.assertEqual(self.actions[-1].status, ActionStatus.SUCCEEDED)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.store.get("s1").unread_count, 1)

    async def test_real_send_failure_keeps_existing_retry_path(self):
        self.accept("old")
        self.now = 105.0
        self.model_release.set()

        async def fail(*_):
            return False

        self.runtime.message_sender.send = fail
        result = await self.runtime.dispatch_deferred(
            RunContext("s1", "old", source_id="old"), now=105.0,
        )
        self.assertFalse(result.delivered)
        self.assertEqual(result.error, "RuntimeError")
        self.assertEqual(self.store.get("s1").next_retry_at, 107.0)
        self.assertEqual(len(self.episodes), 1)

    async def test_started_host_failure_is_recorded_without_retrying_old_reply(self):
        first = self.accept("old")
        self.now = 105.0
        self.model_release.set()

        async def failed_after_new_input(request):
            self.now = 106.0
            self.accept("new")
            return ActionResult(False, "send_failed")

        self.runtime.message_sender = None
        self.runtime.action_executor = ActionExecutor(
            SimpleNamespace(execute=failed_after_new_input),
            ActionLedger(SimpleNamespace(append=self.actions.append)),
            clock=lambda: self.now,
        )
        result = await self.runtime.dispatch_deferred(
            RunContext("s1", "old", source_id=first.source_id), now=105.0,
        )
        self.assertFalse(result.delivered)
        self.assertEqual(result.error, "RuntimeError")
        self.assertEqual(self.actions[-1].status, ActionStatus.FAILED)
        self.assertEqual(len(self.episodes), 1)
        self.assertEqual(self.store.get("s1").next_retry_at, 0.0)
        self.assertEqual(self.store.get("s1").wait_until, 111.0)

    async def test_legacy_sender_failure_after_new_input_keeps_newer_wait(self):
        first = self.accept("old")
        self.now = 105.0
        self.model_release.set()

        async def send_then_fail(session_id, text):
            self.sent.append((session_id, text))
            self.now = 106.0
            self.accept("new")
            return False

        self.runtime.message_sender.send = send_then_fail
        result = await self.runtime.dispatch_deferred(
            RunContext("s1", "old", source_id=first.source_id), now=105.0,
        )
        self.assertFalse(result.delivered)
        self.assertEqual(result.error, "RuntimeError")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(self.episodes), 1)
        self.assertEqual(self.store.get("s1").next_retry_at, 0.0)
        self.assertEqual(self.store.get("s1").wait_until, 111.0)

    async def test_proactive_started_send_failure_does_not_consume_newer_input(self):
        self.accept("old")
        self.runtime.schedule_proactive("s1", 5.0, now=self.now)
        self.now = 105.0
        self.model_release.set()

        async def send_then_fail(session_id, text):
            self.sent.append((session_id, text))
            self.now = 106.0
            self.accept("new")
            return False

        self.runtime.message_sender.send = send_then_fail
        result = await self.runtime.dispatch_proactive(
            RunContext("s1", "topic"), ProactiveDecision(True, "due"), now=105.0,
        )
        self.assertFalse(result.delivered)
        self.assertEqual(result.error, "RuntimeError")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(self.episodes), 1)
        self.assertEqual(self.store.get("s1").proactive_attempts, 0)
        self.assertEqual(self.store.get("s1").wait_until, 111.0)

    async def test_new_input_between_action_attempt_and_host_port_cancels_send(self):
        first = self.accept("old")
        self.now = 105.0
        self.model_release.set()

        class InterruptingSink:
            def append(inner, record):
                self.actions.append(record)
                if record.status is ActionStatus.ATTEMPTED:
                    self.now = 106.0
                    self.accept("new")

        self.runtime.message_sender = None
        self.runtime.action_executor = ActionExecutor(
            SimpleNamespace(execute=self.action_send), ActionLedger(InterruptingSink()),
            clock=lambda: self.now,
        )
        result = await self.runtime.dispatch_deferred(
            RunContext("s1", "old", source_id=first.source_id), now=105.0,
        )
        self.assertEqual(result.error, "superseded")
        self.assertEqual(self.sent, [])
        self.assertEqual([r.status for r in self.actions],
                         [ActionStatus.ATTEMPTED, ActionStatus.CANCELLED])
        self.assertEqual(self.episodes, [])
        self.assertEqual(self.store.get("s1").next_retry_at, 0.0)

    async def test_action_executor_receives_guard_before_host_send(self):
        first = self.accept("old")
        self.now = 105.0
        sink = SimpleNamespace(append=self.actions.append)
        port = SimpleNamespace(execute=lambda request: self.action_send(request))
        self.runtime.message_sender = None
        self.runtime.action_executor = ActionExecutor(port, ActionLedger(sink), clock=lambda: self.now)
        self.model_release.set()
        result = await self.runtime.dispatch_deferred(
            RunContext("s1", "old", source_id=first.source_id), now=self.now,
        )
        self.assertTrue(result.delivered)
        self.assertEqual(self.actions[-1].status, ActionStatus.SUCCEEDED)
        self.assertEqual(len(self.sent), 1)
        sources = self.db.sources.recent_sources(since="", limit=10)
        reply = next(row for row in sources if row.role == "assistant")
        self.assertEqual(reply.reply_to, first.source_id)

    async def action_send(self, request):
        self.sent.append((request.session_id, request.text))
        return ActionResult(True)


if __name__ == "__main__":
    unittest.main()
