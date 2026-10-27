"""Pure AgentRuntime contracts, wake policy and session-state tests."""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.runtime import (  # noqa: E402
    AgentRuntime,
    AttentionLevel,
    InMemoryStateStore,
    JsonStateStore,
    MemoryContext,
    MemoryContextRequest,
    RunContext,
    RuntimeInput,
    SessionState,
    WakeAction,
    WakePolicy,
)


class Trace:
    def __init__(self) -> None:
        self.rows = []

    def record(self, kind, status, context=None):
        self.rows.append((kind, status, context or {}))


class WakePolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = WakePolicy()
        self.state = SessionState(session_id="s1")

    def test_empty_text_is_ignored(self) -> None:
        self.assertEqual(
            self.policy.evaluate(RuntimeInput("s1", ""), self.state, 10).action,
            WakeAction.IGNORE,
        )

    def test_direct_attention_replies(self) -> None:
        decision = self.policy.evaluate(
            RuntimeInput("s1", "hello", mentioned=True), self.state, 10
        )
        self.assertEqual(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.reason, "direct_attention")

    def test_question_replies_without_mention(self) -> None:
        self.assertEqual(
            self.policy.evaluate(
                RuntimeInput("s1", "what time?", question=True), self.state, 10
            ).action,
            WakeAction.REPLY,
        )

    def test_cooldown_ignores_ambient_message(self) -> None:
        self.state.last_spoke_at = 100
        self.state.reply_cooldown_seconds = 30
        decision = self.policy.evaluate(RuntimeInput("s1", "ambient", event_time=110), self.state, 110)
        self.assertEqual(decision.action, WakeAction.IGNORE)
        self.assertEqual(decision.reason, "reply_cooldown")

    def test_quiet_window_does_not_ignore_direct_attention(self) -> None:
        self.state.quiet_until = 200
        decision = self.policy.evaluate(
            RuntimeInput("s1", "hello", mentioned=True, event_time=150), self.state, 150
        )
        self.assertEqual(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.reason, "direct_attention")

    def test_private_always_replies_even_during_wait(self) -> None:
        self.state.wait_until = 200
        decision = self.policy.evaluate(
            RuntimeInput("s1", "hello", private=True, event_time=150), self.state, 150
        )
        self.assertEqual(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.reason, "private_message")
        self.assertTrue(decision.must_reply)

    def test_group_ambient_waits_and_direct_breaks_wait(self) -> None:
        self.state.wait_until = 200
        ambient = self.policy.evaluate(RuntimeInput("s1", "ambient", event_time=150), self.state, 150)
        direct = self.policy.evaluate(
            RuntimeInput("s1", "hello", private=False, mentioned=True, event_time=150),
            self.state,
            150,
        )
        self.assertEqual(ambient.action, WakeAction.WAIT)
        self.assertEqual(direct.action, WakeAction.REPLY)

    def test_addressed_question_breaks_wait(self) -> None:
        self.state.wait_until = 200
        decision = self.policy.evaluate(
            RuntimeInput("s1", "what happened?", question=True, event_time=150),
            self.state,
            150,
        )
        self.assertEqual(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.attention, AttentionLevel.ADDRESSED)

    def test_direct_attention_breaks_wait(self) -> None:
        self.state.wait_until = 200
        decision = self.policy.evaluate(
            RuntimeInput("s1", "hello", mentioned=True, event_time=150), self.state, 150
        )
        self.assertEqual(decision.action, WakeAction.REPLY)
        self.assertEqual(decision.reason, "direct_attention")

    def test_wake_policy_uses_now_not_event_time_for_windows(self) -> None:
        self.state.quiet_until = 150
        decision = self.policy.evaluate(
            RuntimeInput("s1", "ambient", event_time=100), self.state, 200
        )
        self.assertEqual(decision.action, WakeAction.OBSERVE)
        self.assertEqual(decision.reason, "ambient_message")

    def test_wait_expires_at_exact_deadline(self) -> None:
        self.state.wait_until = 200
        decision = self.policy.evaluate(
            RuntimeInput("s1", "hello", mentioned=True, event_time=200), self.state, 200
        )
        self.assertEqual(decision.action, WakeAction.REPLY)

    def test_cooldown_expires_at_exact_deadline(self) -> None:
        self.state.cooldown_until = 130
        decision = self.policy.evaluate(
            RuntimeInput("s1", "ambient", event_time=130), self.state, 130
        )
        self.assertEqual(decision.action, WakeAction.OBSERVE)

    def test_ambient_message_observes(self) -> None:
        self.assertEqual(
            self.policy.evaluate(RuntimeInput("s1", "ambient", event_time=10), self.state, 10).action,
            WakeAction.OBSERVE,
        )


    def test_observe_updates_state_and_trace(self) -> None:
        store = InMemoryStateStore()
        trace = Trace()
        runtime = AgentRuntime(store, trace=trace, clock=lambda: 100)
        decision = runtime.observe(
            RuntimeInput("s1", "hello", mentioned=True, unread_count=3)
        )
        state = store.get("s1")
        self.assertEqual(decision.action, WakeAction.REPLY)
        self.assertEqual(state.last_action, "reply")
        self.assertEqual(state.unread_count, 3)
        self.assertEqual(len(trace.rows), 1)
        self.assertNotIn("hello", str(trace.rows[0]))

    def test_memory_context_port_is_delegated(self) -> None:
        seen = []
        expected = MemoryContext(text="block", info={"final_ids": ("a1",)})

        class Memory:
            def build_context(self, request):
                seen.append(request)
                return expected

        runtime = AgentRuntime(InMemoryStateStore(), memory_context=Memory())
        context = runtime.build_context(RuntimeInput("s1", "hello"))
        self.assertIs(context, expected)
        self.assertIsInstance(seen[0], MemoryContextRequest)
        self.assertEqual(seen[0].session_id, "s1")
        self.assertEqual(seen[0].query, "hello")
        self.assertEqual(context.text, "block")
        self.assertEqual(context.info["final_ids"], ("a1",))

    def test_missing_memory_context_returns_empty_context(self) -> None:
        runtime = AgentRuntime(InMemoryStateStore())
        first = runtime.build_context(RuntimeInput("s1", "hello"))
        second = runtime.build_context(RuntimeInput("s1", "again"))
        self.assertEqual(first.text, "")
        self.assertEqual(first.info, {})
        self.assertIsNot(first.info, second.info)

    def test_observe_uses_runtime_clock_when_event_has_no_timestamp(self) -> None:
        store = InMemoryStateStore()
        runtime = AgentRuntime(store, clock=lambda: 500)
        runtime.observe(RuntimeInput("s1", "ambient"))
        self.assertEqual(store.get("s1").last_seen_at, 500)

    def test_observe_uses_explicit_now_not_event_time(self) -> None:
        store = InMemoryStateStore()
        runtime = AgentRuntime(store, clock=lambda: 100)
        runtime.observe(RuntimeInput("s1", "ambient", event_time=10), now=500)
        state = store.get("s1")
        self.assertEqual(state.last_event_at, 10)
        self.assertEqual(state.last_seen_at, 500)

    def test_stale_event_is_ignored_without_mutating_state(self) -> None:
        store = InMemoryStateStore()
        runtime = AgentRuntime(store, clock=lambda: 100)
        runtime.observe(RuntimeInput("s1", "new", event_time=200), now=200)
        before = store.get("s1")
        decision = runtime.observe(
            RuntimeInput("s1", "old", event_time=100), now=300
        )
        after = store.get("s1")
        self.assertEqual(decision.reason, "stale_event")
        self.assertEqual(after.last_seen_at, before.last_seen_at)
        self.assertEqual(after.last_event_at, before.last_event_at)

    def test_runtime_cooldown_uses_real_timestamps(self) -> None:
        store = InMemoryStateStore()
        runtime = AgentRuntime(store, clock=lambda: 100)
        runtime.observe(
            RuntimeInput("s1", "hello", event_time=100, mentioned=True), now=100
        )
        runtime.mark_delivered("s1", now=100)
        self.assertEqual(store.get("s1").cooldown_until, 130)
        self.assertEqual(
            runtime.observe(
                RuntimeInput("s1", "ambient", event_time=110), now=110
            ).action,
            WakeAction.IGNORE,
        )
        self.assertEqual(
            runtime.observe(
                RuntimeInput("s1", "ambient", event_time=140), now=140
            ).action,
            WakeAction.OBSERVE,
        )

    def test_runtime_quiet_and_wait_transitions(self) -> None:
        store = InMemoryStateStore()
        runtime = AgentRuntime(store, clock=lambda: 100)
        state = store.get("s1")
        state.quiet_until = 130
        store.put(state)
        self.assertEqual(
            runtime.observe(
                RuntimeInput("s1", "hello", event_time=110), now=110
            ).action,
            WakeAction.IGNORE,
        )
        state = store.get("s1")
        state.quiet_until = 0.0
        state.wait_until = 170
        store.put(state)
        self.assertEqual(
            runtime.observe(
                RuntimeInput("s1", "ambient", event_time=150), now=150
            ).action,
            WakeAction.WAIT,
        )
        self.assertEqual(
            runtime.observe(
                RuntimeInput("s1", "ambient", event_time=180), now=180
            ).action,
            WakeAction.OBSERVE,
        )

    def test_runtime_advances_read_through_watermark_on_delivery(self) -> None:
        store = InMemoryStateStore()
        runtime = AgentRuntime(store, clock=lambda: 100)
        runtime.observe(
            RuntimeInput("s1", "hello", unread_count=3, unread_seq=7)
        )
        state = runtime.mark_delivered("s1", now=200)
        self.assertEqual(state.read_through_seq, 7)
        self.assertEqual(state.unread_count, 0)

    def test_dispatch_claim_and_retry_are_bounded(self) -> None:
        store = InMemoryStateStore()
        runtime = AgentRuntime(store, clock=lambda: 100)
        self.assertEqual(runtime.claim_dispatch("s1", "src1", now=100), 1)
        self.assertEqual(runtime.claim_dispatch("s1", "src1", now=100), 2)
        state = runtime.schedule_retry("s1", 100, attempts=2, max_attempts=3)
        self.assertGreater(state.wait_until, 100)
        self.assertEqual(state.next_retry_at, state.wait_until)
        dead = runtime.schedule_retry("s1", 100, attempts=3, max_attempts=3)
        self.assertEqual(dead.wait_until, 0.0)
        self.assertEqual(dead.next_retry_at, 0.0)
        self.assertEqual(dead.last_reason, "dispatch_dead")
        self.assertEqual(runtime.claim_dispatch("s1", "src2", now=110), 1)

    def test_ambient_observe_sets_wait_deadline(self) -> None:
        store = InMemoryStateStore()
        runtime = AgentRuntime(store, clock=lambda: 100, wait_seconds=5)
        runtime.observe(RuntimeInput("s1", "ambient"))
        self.assertEqual(store.get("s1").wait_until, 105)

    def test_ambient_wait_extends_on_new_traffic(self) -> None:
        store = InMemoryStateStore()
        runtime = AgentRuntime(store, clock=lambda: 100, wait_seconds=5)
        runtime.observe(RuntimeInput("s1", "first", event_time=100), now=100)
        self.assertEqual(store.get("s1").wait_until, 105)
        runtime.observe(RuntimeInput("s1", "second", event_time=102), now=102)
        self.assertEqual(store.get("s1").wait_until, 107)

    def test_delivery_clears_unread_and_updates_last_spoke(self) -> None:
        store = InMemoryStateStore()
        runtime = AgentRuntime(store, clock=lambda: 200)
        runtime.observe(RuntimeInput("s1", "hello", mentioned=True, unread_count=2))
        state = runtime.mark_delivered("s1")
        self.assertEqual(state.unread_count, 0)
        self.assertEqual(state.last_spoke_at, 200)

    def test_json_state_store_survives_instances(self) -> None:
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_runtime_state_"), "state.json")
        first = JsonStateStore(path)
        state = first.get("s1")
        state.quiet_until = 123
        state.unread_count = 4
        first.put(state)
        second = JsonStateStore(path)
        loaded = second.get("s1")
        self.assertEqual(loaded.quiet_until, 123)
        self.assertEqual(loaded.unread_count, 4)

    def test_runtime_surface_has_no_test_only_mutators(self) -> None:
        for name in ("quiet", "wait", "mark_read"):
            self.assertFalse(hasattr(AgentRuntime, name))

    def test_decision_actions_are_the_production_set(self) -> None:
        self.assertEqual(
            {action.value for action in WakeAction},
            {"ignore", "observe", "wait", "reply"},
        )

    def test_json_state_store_defaults_legacy_removed_fields(self) -> None:
        import json

        path = os.path.join(
            tempfile.mkdtemp(prefix="seekmem_legacy_state_"), "state.json"
        )
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({
                "s1": {
                    "session_id": "s1",
                    "quiet_until": 123,
                    "last_wake_at": 9,
                    "reply_count": 4,
                }
            }, handle)
        store = JsonStateStore(path)
        state = store.get("s1")
        self.assertEqual(state.session_id, "s1")
        self.assertEqual(state.quiet_until, 123)
        self.assertEqual(state.wait_until, 0.0)
        self.assertEqual(state.next_retry_at, 0.0)
        self.assertEqual(state.reply_cooldown_seconds, 30.0)
        runtime = AgentRuntime(store, clock=lambda: 200)
        runtime.observe(RuntimeInput("s1", "ambient", event_time=200), now=200)
        runtime.mark_delivered("s1", now=200)

    def test_deferred_dispatch_owns_generate_send_and_record(self) -> None:
        class Model:
            def __init__(self):
                self.calls = []

            async def complete(self, session_id, prompt, system_prompt=None):
                self.calls.append((session_id, prompt, system_prompt))
                return "deferred reply"

        class Sender:
            def __init__(self):
                self.sent = []

            async def send(self, session_id, text):
                self.sent.append((session_id, text))
                return True

        class Recorder:
            def __init__(self):
                self.replies = []
                self.errors = []

            def new_run_id(self):
                return "run-1"

            def record_deferred_reply(self, **kwargs):
                self.replies.append(kwargs)
                return SimpleNamespace(
                    response_chars=len(kwargs["text"]),
                    assistant_source_id="a1",
                )

            def record_deferred_error(self, **kwargs):
                self.errors.append(kwargs)

        store = InMemoryStateStore()
        state = store.get("s1")
        state.wait_until = 100
        store.put(state)
        model, sender, recorder = Model(), Sender(), Recorder()
        runtime = AgentRuntime(
            store,
            clock=lambda: 100,
            memory_context=SimpleNamespace(
                build_context=lambda event: MemoryContext(text="memory")
            ),
            model_gateway=model,
            message_sender=sender,
            recorder=recorder,
        )
        result = asyncio.run(runtime.dispatch_deferred(RunContext(
            session_id="s1", text="hello", source_id="u1", bot_id="bot", event_time=100,
        )))
        self.assertTrue(result.delivered)
        self.assertEqual(result.assistant_source_id, "a1")
        self.assertEqual(model.calls, [("s1", "hello", "memory")])
        self.assertEqual(sender.sent, [("s1", "deferred reply")])
        self.assertEqual(recorder.replies[0]["run_id"], "run-1")
        self.assertEqual(store.get("s1").wait_until, 0.0)

    def test_deferred_dispatch_rejects_not_due_state(self) -> None:
        class Model:
            def __init__(self):
                self.calls = 0

            async def complete(self, session_id, prompt, system_prompt=None):
                self.calls += 1
                return "must not run"

        class Sender:
            async def send(self, session_id, text):
                raise AssertionError("must not send")

        class Recorder:
            def new_run_id(self):
                return "run-id"

            def record_deferred_reply(self, **kwargs):
                raise AssertionError("must not record")

            def record_deferred_error(self, **kwargs):
                raise AssertionError("must not record")

        store = InMemoryStateStore()
        state = store.get("s1")
        state.wait_until = 300
        store.put(state)
        model = Model()
        runtime = AgentRuntime(
            store,
            clock=lambda: 100,
            model_gateway=model,
            message_sender=Sender(),
            recorder=Recorder(),
        )
        result = asyncio.run(runtime.dispatch_deferred(RunContext(
            session_id="s1", text="hello", source_id="u1", event_time=500,
        )))
        self.assertFalse(result.delivered)
        self.assertEqual(result.error, "not_due")
        self.assertEqual(model.calls, 0)

    def test_deferred_empty_source_cannot_clear_future_wait(self) -> None:
        store = InMemoryStateStore()
        state = store.get("s1")
        state.wait_until = 300
        store.put(state)
        runtime = AgentRuntime(store, clock=lambda: 100)
        result = asyncio.run(runtime.dispatch_deferred(RunContext(
            session_id="s1", text="", source_id="", event_time=100,
        )))
        self.assertFalse(result.delivered)
        self.assertEqual(result.error, "not_due")
        self.assertEqual(store.get("s1").wait_until, 300)

    def test_deferred_missing_ports_returns_safe_errors(self) -> None:
        class Model:
            async def complete(self, session_id, prompt, system_prompt=None):
                return "reply"

        class Sender:
            async def send(self, session_id, text):
                return True

        store = InMemoryStateStore()
        state = store.get("s1")
        state.wait_until = 100
        store.put(state)
        runtime = AgentRuntime(store, clock=lambda: 100)
        result = asyncio.run(runtime.dispatch_deferred(RunContext(
            session_id="s1", text="hello", source_id="u1", event_time=100,
        )))
        self.assertEqual(result.error, "runtime_port_missing")
        self.assertEqual(store.get("s1").wait_until, 100)

        runtime = AgentRuntime(
            store,
            clock=lambda: 100,
            model_gateway=Model(),
            message_sender=Sender(),
        )
        result = asyncio.run(runtime.dispatch_deferred(RunContext(
            session_id="s1", text="hello", source_id="u1", event_time=100,
        )))
        self.assertEqual(result.error, "recorder_missing")
        self.assertEqual(store.get("s1").wait_until, 100)

    def test_deferred_dispatch_failure_schedules_retry_without_raising(self) -> None:
        class Model:
            async def complete(self, session_id, prompt, system_prompt=None):
                raise RuntimeError("secret provider detail")

        class Sender:
            async def send(self, session_id, text):
                return True

        class Recorder:
            def __init__(self):
                self.errors = []

            def new_run_id(self):
                return "run-fail"

            def record_deferred_reply(self, **kwargs):
                raise AssertionError("must not record a reply")

            def record_deferred_error(self, **kwargs):
                self.errors.append(kwargs)

        store = InMemoryStateStore()
        state = store.get("s1")
        state.wait_until = 100
        store.put(state)
        recorder = Recorder()
        runtime = AgentRuntime(
            store,
            clock=lambda: 100,
            model_gateway=Model(),
            message_sender=Sender(),
            recorder=recorder,
        )
        result = asyncio.run(runtime.dispatch_deferred(RunContext(
            session_id="s1", text="hello", source_id="u1", event_time=100,
        )))
        self.assertFalse(result.delivered)
        self.assertEqual(result.error, "RuntimeError")
        self.assertEqual(recorder.errors[0]["error"].__class__, RuntimeError)
        state = store.get("s1")
        self.assertGreater(state.wait_until, 100)
        self.assertEqual(state.next_retry_at, state.wait_until)

    def test_runtime_package_does_not_import_astrbot(self) -> None:
        root = Path(__file__).resolve().parents[1] / "app" / "runtime"
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("import astrbot", text)
            self.assertNotIn("from astrbot", text)


class AgentRuntimeNormalPathTest(unittest.TestCase):
    def setUp(self) -> None:
        class Recorder:
            def __init__(self):
                self.users = []
                self.replies = []
                self.deliveries = []
                self.errors = []

            def record_user(self, **kwargs):
                self.users.append(kwargs)
                return SimpleNamespace(source_id="u1", turn_id="t1")

            def record_reply(self, **kwargs):
                self.replies.append(kwargs)
                return SimpleNamespace(
                    run_id=kwargs["run_id"],
                    turn_id=kwargs["turn_id"],
                    assistant_source_id="a1",
                    response_chars=len(kwargs["text"]),
                )

            def record_delivery(self, **kwargs):
                self.deliveries.append(kwargs)

            def record_error(self, **kwargs):
                self.errors.append(kwargs)

        self.recorder = Recorder()
        self.store = InMemoryStateStore()
        self.runtime = AgentRuntime(
            self.store,
            clock=lambda: 200,
            recorder=self.recorder,
        )

    def test_accept_user_records_then_observes(self) -> None:
        receipt = self.runtime.accept_user(
            RuntimeInput("s1", "hello", speaker_id="u1", mentioned=True, event_time=100),
            event_id="e1",
            deferred=True,
        )
        self.assertEqual((receipt.source_id, receipt.turn_id), ("u1", "t1"))
        self.assertEqual(receipt.decision.action, WakeAction.REPLY)
        self.assertEqual(self.recorder.users[0]["event_id"], "e1")
        self.assertTrue(self.recorder.users[0]["deferred"])
        self.assertEqual(self.store.get("s1").last_action, "reply")

    def test_reply_delivery_and_error_use_recorder_owner(self) -> None:
        self.runtime.observe(RuntimeInput("s1", "hello", mentioned=True, event_time=100))
        reply = self.runtime.record_reply(
            run_id="run-1",
            session_id="s1",
            text="answer",
            speaker_id="bot",
            turn_id="t1",
            reply_to="u1",
        )
        self.assertEqual(reply.assistant_source_id, "a1")
        self.runtime.record_delivery(
            run_id="run-1",
            session_id="s1",
            decision="reply",
            reason="direct_attention",
            response_chars=6,
            user_source_id="u1",
            assistant_source_id="a1",
            now=200,
        )
        self.runtime.record_error(
            run_id="run-2",
            session_id="s1",
            decision="reply",
            reason="agent_error",
            error="agent_error",
            user_source_id="u1",
        )
        self.assertEqual(self.recorder.replies[0]["run_id"], "run-1")
        self.assertEqual(self.recorder.deliveries[0]["assistant_source_id"], "a1")
        self.assertEqual(self.recorder.errors[0]["run_id"], "run-2")
        self.assertEqual(self.store.get("s1").last_spoke_at, 200)


if __name__ == "__main__":
    unittest.main()
