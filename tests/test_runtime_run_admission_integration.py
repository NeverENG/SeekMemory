"""Source-backed input admission, supersession and retryable acceptance failures."""

from __future__ import annotations

import gc
import sys
import unittest
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from weakref import ref

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime import AgentRuntime, DefaultAttentionPolicy, InMemoryStateStore, RunRecorder  # noqa: E402
from app.runtime.contracts import (  # noqa: E402
    AttentionDecision, RunDecision, RunKind, RunTransition, RunTrigger, RuntimeInput, WakeAction,
)
from app.runtime.scheduler import Scheduler  # noqa: E402
from store import open_store  # noqa: E402


class RuntimeRunAdmissionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.store = InMemoryStateStore()
        self.now = 100.0
        self.rows = []
        self.recorder = RunRecorder(sources=self.db.sources, buffer=None, checkpoint=None, episodes=None)
        self.runtime = self.make_runtime()

    def make_runtime(self, **kwargs):
        return AgentRuntime(
            self.store, recorder=self.recorder, clock=lambda: self.now, wait_seconds=5.0,
            trace=SimpleNamespace(record=lambda *row: self.rows.append(row)),
            run_control_enabled=True, **kwargs,
        )

    def event(self, event_id="e1", *, lane="s1", at=100.0, speaker="u1", text="hello", private=True):
        return RuntimeInput(lane, text, event_time=at, speaker_id=speaker, private=private, event_id=event_id)

    def begin(self, event, receipt):
        return self.runtime.begin_run(
            event.session_id, RunTrigger(RunKind.USER, event, self.now), receipt=receipt,
        )

    def source_count(self):
        return len(self.db.sources.recent_sources(since="", limit=100))

    def test_run_control_is_opt_in_and_requires_source_identity(self) -> None:
        runtime = AgentRuntime(self.store)
        self.assertIsNone(runtime.begin_run("s1", RunTrigger(RunKind.DEFERRED, None, self.now)))
        with self.assertRaises(ValueError):
            AgentRuntime(self.store, run_control_enabled=True)

    def test_distinct_equal_time_inputs_reject_late_old_admission(self) -> None:
        for at in (100.0, 0.0):
            with self.subTest(event_time=at):
                lane = f"lane-{at}"
                first = self.event("e1", lane=lane, at=at)
                second = self.event("e2", lane=lane, at=at)
                a = self.runtime.accept_user(first)
                old = self.begin(first, a)
                b = self.runtime.accept_user(second)
                self.assertNotEqual(a.source_id, b.source_id)
                self.assertTrue(old.is_superseded())
                self.assertIsNone(self.begin(first, a))
                current = self.begin(second, b)
                self.assertIsNotNone(current)
                self.runtime.finish_run(old)
                self.assertIs(self.runtime.current_run(lane), current)
        self.assertEqual(self.source_count(), 4)

    def test_old_replay_preserves_current_and_finished_lanes(self) -> None:
        for at in (100.0, 0.0):
            with self.subTest(event_time=at):
                lane = f"lane-{at}"
                first, second = self.event("e1", lane=lane, at=at), self.event("e2", lane=lane, at=at)
                a = self.runtime.accept_user(first)
                self.begin(first, a)
                b = self.runtime.accept_user(second)
                current = self.begin(second, b)
                before = asdict(self.store.get(lane))
                replay = self.runtime.accept_user(first)
                self.assertEqual(replay.source_id, a.source_id)
                self.assertEqual(replay.decision.reason, "replayed_event")
                self.assertIs(replay.decision.action, WakeAction.IGNORE)
                self.assertIsNone(replay.read_through_seq)
                self.assertIsNone(self.begin(first, replay))
                self.assertFalse(current.is_superseded())
                self.assertEqual(asdict(self.store.get(lane)), before)
                self.runtime.finish_run(current)
                replay = self.runtime.accept_user(first)
                self.assertEqual(replay.decision.reason, "replayed_event")
                self.assertIsNone(self.begin(first, replay))
                self.assertIsNone(self.runtime.current_run(lane))
                self.assertEqual(asdict(self.store.get(lane)), before)
        self.assertEqual(self.source_count(), 4)

    def test_unstarted_old_input_cannot_supersede_a_newer_run(self) -> None:
        first, second = self.event("e1", at=0.0), self.event("e2", at=0.0)
        a = self.runtime.accept_user(first)
        b = self.runtime.accept_user(second)
        current = self.begin(second, b)
        self.assertIsNone(self.begin(first, a))
        self.assertFalse(current.is_superseded())
        self.assertIs(self.runtime.current_run("s1"), current)

    def test_reused_event_id_respects_lane_and_speaker_identity(self) -> None:
        first = self.event()
        other = self.event(lane="s2")
        next_speaker = self.event(speaker="u2")
        a, b = self.runtime.accept_user(first), self.runtime.accept_user(other)
        old, other_run = self.begin(first, a), self.begin(other, b)
        c = self.runtime.accept_user(next_speaker)
        current = self.begin(next_speaker, c)
        self.assertEqual(len({a.source_id, b.source_id, c.source_id}), 3)
        self.assertTrue(old.is_superseded())
        self.assertFalse(other_run.is_superseded())
        self.assertGreater(current.epoch, other_run.epoch)
        self.assertGreater(other_run.epoch, old.epoch)
        self.assertEqual(self.source_count(), 3)

    def test_stale_and_empty_input_preserve_current_work(self) -> None:
        event = self.event(at=200.0)
        current = self.begin(event, self.runtime.accept_user(event))
        before = asdict(self.store.get("s1"))
        stale = self.runtime.accept_user(self.event("old", at=100.0))
        self.assertEqual(stale.decision.reason, "stale_event")
        self.assertIsNone(stale.read_through_seq)
        self.assertIsNone(self.begin(self.event("old", at=100.0), stale))
        empty = self.runtime.accept_user(self.event("empty", text="  "))
        self.assertEqual(empty.decision.reason, "empty_text")
        self.assertFalse(current.is_superseded())
        self.assertEqual(asdict(self.store.get("s1")), before)
        self.assertEqual(self.source_count(), 2)

    def test_user_begin_requires_a_current_single_use_acceptance(self) -> None:
        event = self.event()
        receipt = self.runtime.accept_user(event)
        trigger = RunTrigger(RunKind.USER, event, self.now)
        self.assertIsNone(self.runtime.begin_run("s1", trigger))
        self.assertIsNone(self.runtime.begin_run("s2", trigger, receipt=receipt))
        self.assertIsNone(self.runtime.begin_run(
            "s1", RunTrigger(RunKind.USER, None, self.now), receipt=receipt,
        ))
        current = self.begin(event, receipt)
        self.assertIsNotNone(current)
        self.assertIsNone(self.begin(event, receipt))
        self.runtime.finish_run(current)
        self.assertIsNone(self.begin(event, receipt))
        self.assertIsNone(self.runtime.current_run("s1"))

    def test_enabled_acceptance_requires_identity_and_owns_attention(self) -> None:
        event = self.event("")
        before = asdict(self.store.get("s1"))
        with self.assertRaisesRegex(ValueError, "stable event ID"):
            self.runtime.accept_user(event)
        with self.assertRaisesRegex(ValueError, "owns attention"):
            self.runtime.accept_user(self.event(), decision=RunDecision(WakeAction.REPLY, "cached"))
        self.assertEqual(self.source_count(), 0)
        self.assertEqual(asdict(self.store.get("s1")), before)
        receipt = self.runtime.accept_user(event, event_id="host-id")
        self.assertIsNotNone(self.begin(event, receipt))
        self.assertEqual(self.runtime.accept_user(event, event_id="host-id").decision.reason, "replayed_event")

    def test_disabled_path_keeps_precomputed_attention_and_missing_id_compatible(self) -> None:
        runtime = AgentRuntime(self.store, recorder=self.recorder)
        event = self.event("")
        decision = runtime.observe(event)
        before = asdict(self.store.get("s1"))
        receipt = runtime.accept_user(event, decision=decision)
        self.assertEqual(receipt.decision, decision)
        self.assertEqual(receipt.read_through_seq, 1)
        self.assertEqual(asdict(self.store.get("s1")), before)
        self.assertIsNone(runtime.current_run("s1"))

    def test_copied_foreign_or_mismatched_receipts_cannot_start_work(self) -> None:
        event = self.event()
        receipt = self.runtime.accept_user(event)
        self.assertIsNone(self.begin(event, replace(receipt)))
        self.assertIsNone(self.begin(replace(event, text="different input"), receipt))
        other = AgentRuntime(InMemoryStateStore(), recorder=RunRecorder(
            sources=self.db.sources, buffer=None, checkpoint=None, episodes=None,
        ), run_control_enabled=True)
        foreign = other.accept_user(event)
        self.assertEqual(receipt, foreign)
        self.assertIsNone(self.begin(event, foreign))
        self.assertIsNone(other.begin_run("s1", RunTrigger(RunKind.USER, event, self.now), receipt=receipt))
        self.assertIsNotNone(self.begin(event, receipt))

    def test_user_admission_rechecks_background_work_started_after_acceptance(self) -> None:
        event = self.event()
        receipt = self.runtime.accept_user(event)
        self.assertIsNone(self.runtime.current_run("s1"))
        background = self.runtime.begin_run("s1", RunTrigger(RunKind.PROACTIVE, None, self.now))
        self.assertIsNotNone(background)
        user = self.begin(event, receipt)
        self.assertIsNotNone(user)
        self.assertTrue(background.is_superseded())
        self.runtime.finish_run(background)
        self.assertIs(self.runtime.current_run("s1"), user)

    def test_background_delivery_consumes_unstarted_user_input(self) -> None:
        event = self.event()
        receipt = self.runtime.accept_user(event)
        background = self.runtime.begin_run("s1", RunTrigger(RunKind.DEFERRED, None, self.now))
        self.runtime.record_delivery(
            run_id=background.run_id, session_id="s1", decision="reply", reason="deferred",
            read_through_seq=receipt.read_through_seq,
        )
        self.runtime.finish_run(background)
        self.assertEqual(self.store.get("s1").unread_count, 0)
        self.assertIsNone(self.begin(event, receipt))
        self.assertIsNone(self.runtime.current_run("s1"))

    def test_admission_releases_inputs_on_claim_or_abandoned_receipt(self) -> None:
        for claim in (False, True):
            with self.subTest(claim=claim):
                event = self.event(lane=f"lane-{claim}")
                receipt = self.runtime.accept_user(event)
                event_ref, receipt_ref = ref(event), ref(receipt)
                if claim:
                    self.runtime.finish_run(self.begin(event, receipt))
                del event
                if not claim:
                    del receipt
                gc.collect()
                self.assertIsNone(event_ref())
                if not claim:
                    self.assertIsNone(receipt_ref())

    def test_unsupported_policy_deferral_falls_back_and_preserves_new_input(self) -> None:
        for mode in ("keep_active", "drop_new"):
            with self.subTest(mode=mode):
                def decide(state, trigger, active):
                    if mode == "keep_active":
                        return RunTransition(start_new=active is None)
                    return RunTransition(start_new=False, supersede_active=True)

                self.runtime = self.make_runtime(run_policy=SimpleNamespace(decide=decide))
                lane = f"lane-{mode}"
                first, second = self.event("e1", lane=lane), self.event("e2", lane=lane, at=101.0)
                a = self.runtime.accept_user(first)
                old = self.begin(first, a)
                b = self.runtime.accept_user(second)
                current = self.begin(second, b)
                self.assertTrue(old.is_superseded())
                self.assertIsNotNone(current)
                self.runtime.record_delivery(
                    run_id=old.run_id, session_id=lane, decision="reply", reason="private",
                    read_through_seq=a.read_through_seq, now=102.0,
                )
                self.runtime.finish_run(old)
                self.assertIs(self.runtime.current_run(lane), current)
                self.assertEqual(self.store.get(lane).unread_count, 1)
                self.assertIn("run_policy_fallback", [row[1] for row in self.rows])
        self.assertEqual(self.source_count(), 4)

    def test_background_rejection_preserves_due_opportunities(self) -> None:
        ambient = self.event("ambient", private=False)
        receipt = self.runtime.accept_user(ambient)
        self.assertIs(receipt.decision.action, WakeAction.OBSERVE)
        self.assertIsNone(self.begin(ambient, receipt))
        self.assertIsNone(self.runtime.current_run("s1"))
        event = self.event("direct", at=101.0)
        current = self.begin(event, self.runtime.accept_user(event))
        self.runtime.schedule_proactive("s1", 0.0, now=101.0)
        before = asdict(self.store.get("s1"))
        for kind in (RunKind.DEFERRED, RunKind.PROACTIVE):
            self.assertIsNone(self.runtime.begin_run("s1", RunTrigger(kind, None, 110.0)))
        self.assertEqual(asdict(self.store.get("s1")), before)
        self.assertFalse(current.is_superseded())
        self.runtime.finish_run(current)
        self.assertTrue(Scheduler(self.store).due(["s1"], now=110.0))
        self.assertIsNotNone(self.runtime.begin_run("s1", RunTrigger(RunKind.PROACTIVE, None, 110.0)))
        self.assertEqual(asdict(self.store.get("s1")), before)

    def test_wait_is_reconsidered_when_new_input_arrives(self) -> None:
        class WaitPolicy(DefaultAttentionPolicy):
            def evaluate(self, event, state, now):
                if not event.private:
                    return AttentionDecision(WakeAction.WAIT, "wait")
                return super().evaluate(event, state, now)

        self.runtime.policy = WaitPolicy()
        waiting = self.event("waiting", private=False)
        receipt = self.runtime.accept_user(waiting)
        self.assertIs(receipt.decision.action, WakeAction.WAIT)
        self.assertIsNone(self.begin(waiting, receipt))
        self.assertIsNone(self.runtime.current_run("s1"))
        old = self.runtime.begin_run("s1", RunTrigger(RunKind.DEFERRED, None, 105.0))
        event = self.event("direct", at=106.0)
        new = self.runtime.accept_user(event, now=106.0)
        self.assertIs(new.decision.action, WakeAction.REPLY)
        self.assertTrue(old.is_superseded())
        self.assertIsNotNone(self.begin(event, new))
        self.assertEqual(self.store.get("s1").unread_count, 2)

    def test_policy_exception_uses_snapshot_and_sanitized_fallback(self) -> None:
        class BrokenPolicy:
            def decide(self, state, trigger, active):
                state.followup_by_speaker["private identity"] = 99
                state.wait_until = 999.0
                raise RuntimeError("private failure")

        self.runtime = self.make_runtime(run_policy=BrokenPolicy())
        event = self.event(lane="private-lane", text="private input")
        old = self.begin(event, self.runtime.accept_user(event))
        self.runtime.accept_user(self.event("e2", lane="private-lane", at=101.0))
        self.assertTrue(old.is_superseded())
        state = self.store.get("private-lane")
        self.assertNotIn("private identity", state.followup_by_speaker)
        self.assertEqual(state.wait_until, 0.0)
        self.assertIn("run_policy_failed", [row[1] for row in self.rows])
        for secret in ("private-lane", "private input", "private identity", "private failure"):
            self.assertNotIn(secret, str(self.rows))

    def test_state_failure_can_retry_acceptance_without_losing_input(self) -> None:
        event = self.event()
        old = self.begin(event, self.runtime.accept_user(event))
        before = asdict(self.store.get("s1"))
        save = self.store.put

        def fail(state):
            raise OSError("unavailable")

        self.store.put = fail
        second = self.event("e2", at=101.0)
        with self.assertRaises(OSError):
            self.runtime.accept_user(second)
        self.assertFalse(old.is_superseded())
        self.assertEqual(asdict(self.store.get("s1")), before)
        self.store.put = save
        new = self.runtime.accept_user(second)
        self.assertEqual(new.read_through_seq, 2)
        self.assertTrue(old.is_superseded())
        self.assertIsNotNone(self.begin(second, new))
        self.assertEqual(self.source_count(), 2)
        self.assertEqual(self.runtime.accept_user(second).decision.reason, "replayed_event")
        self.assertEqual(self.store.get("s1").last_unread_seq, 2)

    def test_failed_acceptance_retry_respects_known_time_and_completion_order(self) -> None:
        for at in (100.0, 0.0):
            with self.subTest(event_time=at):
                lane = f"retry-{at}"
                earlier = self.event("earlier", lane=lane, at=at)
                save = self.store.put
                def fail(state):
                    raise OSError("unavailable")
                self.store.put = fail
                with self.assertRaises(OSError):
                    self.runtime.accept_user(earlier)
                self.store.put = save
                later = self.event("later", lane=lane, at=at + 1 if at else 0.0)
                current = self.begin(later, self.runtime.accept_user(later))
                retry = self.runtime.accept_user(earlier)
                if at:
                    self.assertEqual(retry.decision.reason, "stale_event")
                    self.assertIsNone(self.begin(earlier, retry))
                    self.assertFalse(current.is_superseded())
                    self.assertEqual(self.store.get(lane).last_unread_seq, 1)
                else:
                    self.assertEqual(retry.read_through_seq, 2)
                    self.assertTrue(current.is_superseded())
                    self.assertIsNotNone(self.begin(earlier, retry))
                self.assertEqual(self.runtime.accept_user(earlier).decision.reason, "replayed_event")
        self.assertEqual(self.source_count(), 4)

    def test_capture_failures_remain_retryable_after_direct_or_background_completion(self) -> None:
        for failure in ("source", "projection", "projection_background"):
            with self.subTest(failure=failure):
                lane = f"lane-{failure}"
                self.recorder.buffer = None
                event = self.event(lane=lane)
                old = self.begin(event, self.runtime.accept_user(event))
                second = self.event("e2", lane=lane, at=101.0)

                def fail(*args, **kwargs):
                    raise OSError("unavailable")

                if failure == "source":
                    self.recorder.sources = SimpleNamespace(append_sources=fail)
                else:
                    self.recorder.buffer = SimpleNamespace(add=fail)
                with self.assertRaises(OSError):
                    self.runtime.accept_user(second)
                self.assertFalse(old.is_superseded())
                self.assertEqual(self.store.get(lane).last_unread_seq, 1)
                self.recorder.sources = self.db.sources
                self.recorder.buffer = SimpleNamespace(add=lambda *args, **kwargs: None)
                if failure == "projection_background":
                    self.runtime.retry_writebacks()
                    self.assertFalse(old.is_superseded())
                    self.assertEqual(self.store.get(lane).last_unread_seq, 1)
                new = self.runtime.accept_user(second)
                self.assertEqual(new.read_through_seq, 2)
                self.assertTrue(old.is_superseded())
                self.assertIsNotNone(self.begin(second, new))
                replay = self.runtime.accept_user(second)
                self.assertEqual(replay.decision.reason, "replayed_event")
        self.assertEqual(self.source_count(), 6)

    def test_invalid_policy_result_falls_back_to_default_admission(self) -> None:
        self.runtime = self.make_runtime(run_policy=SimpleNamespace(decide=lambda *args: None))
        first, second = self.event(), self.event("e2", at=101.0)
        old = self.begin(first, self.runtime.accept_user(first))
        new = self.runtime.accept_user(second)
        self.assertTrue(old.is_superseded())
        self.assertIsNotNone(self.begin(second, new))
        self.assertIn("run_policy_failed", [row[1] for row in self.rows])

    def test_supersession_trace_is_idempotent_and_contains_only_run_metadata(self) -> None:
        event = self.event(lane="private-lane", text="private input")
        old = self.begin(event, self.runtime.accept_user(event))
        self.assertTrue(self.runtime.supersede_run("private-lane", old.run_id, "private reason"))
        self.assertFalse(self.runtime.supersede_run("private-lane", old.run_id))
        rows = [row for row in self.rows if row[1] == "run_superseded"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0][2]), {"run_id", "epoch", "kind"})
        for secret in ("private-lane", "private input", "private reason"):
            self.assertNotIn(secret, str(self.rows))

    def test_trace_failure_cannot_block_policy_fallback(self) -> None:
        class BrokenPolicy:
            def decide(self, state, trigger, active):
                raise RuntimeError("unavailable")

        def fail(*args, **kwargs):
            raise OSError("unavailable")

        self.runtime = AgentRuntime(
            self.store, recorder=self.recorder, run_control_enabled=True,
            run_policy=BrokenPolicy(), trace=SimpleNamespace(record=fail),
        )
        first, second = self.event(), self.event("e2", at=101.0)
        old = self.begin(first, self.runtime.accept_user(first))
        new = self.runtime.accept_user(second)
        self.assertTrue(old.is_superseded())
        self.assertIsNotNone(self.begin(second, new))


if __name__ == "__main__":
    unittest.main()
