"""Confirmed delivery retries only writes, never model calls or sending."""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime import (
    AgentRuntime, EpisodeRecord, EpisodeRecorder, InMemoryStateStore,
    JsonStateStore, JsonlEpisodeStore, ProactiveDecision, RepoEpisodeStore,
    RunContext, RunRecorder, RuntimeInput, RuntimeWorker, Scheduler, SessionState,
)
from store import open_store


class WritebackTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.now = 100.0
        self.calls = self.sends = 0
        self.sources, self.projections, self.episodes = [], [], []
        self.fail = ""
        self.store = InMemoryStateStore()
        self.runtime = AgentRuntime(
            self.store, wait_seconds=5, clock=lambda: self.now,
            model_gateway=SimpleNamespace(complete=self.complete),
            message_sender=SimpleNamespace(send=self.send),
            recorder=RunRecorder(
                sources=SimpleNamespace(append_sources=self.append_sources),
                buffer=SimpleNamespace(add=self.project), checkpoint=None,
                episodes=SimpleNamespace(record=self.audit),
            ),
        )
        self.receipt = self.runtime.accept_user(RuntimeInput("s1", "old", event_time=100), event_id="u1")
        self.now = 105
        self.context = RunContext("s1", "old", source_id="u1", run_id="run-1")

    async def complete(self, *args):
        self.calls += 1
        return "reply"

    async def send(self, *args):
        self.sends += 1
        return True

    def append_sources(self, sources):
        if self.fail == "source" and sources[0].role == "assistant":
            raise OSError("private source error")
        self.sources.extend(sources)
        return len(sources)

    def project(self, *args, **kwargs):
        if self.fail == "projection" and kwargs.get("role") == "assistant":
            raise OSError("private projection error")
        self.projections.append(args)

    def audit(self, episode):
        if self.fail == "audit":
            raise OSError("private audit error")
        self.episodes.append(episode)

    def worker(self, enabled=False):
        return RuntimeWorker(
            runtime=self.runtime, scheduler=Scheduler(self.store),
            enabled=lambda: enabled, session_ids=lambda limit: ["s1"],
            run_context=lambda sid, now: self.context, interval_seconds=lambda: 1,
            max_attempts=lambda: 3, base_seconds=lambda: 2, clock=lambda: self.now,
        )

    async def test_each_write_stage_can_fail_without_resending(self):
        for phase in ("source", "projection", "audit"):
            with self.subTest(phase=phase):
                self.setUp()
                self.fail = phase
                result = await self.runtime.dispatch_deferred(self.context)
                self.assertTrue(result.delivered)
                self.assertEqual(result.error, "writeback_pending")
                repeated = await self.runtime.dispatch_deferred(self.context)
                self.assertTrue(repeated.delivered)
                self.assertEqual((self.calls, self.sends), (1, 1))
                self.fail = ""
                self.runtime.retry_writebacks()
                again = await self.runtime.dispatch_deferred(self.context)
                self.assertTrue(again.delivered)
                self.assertEqual(again.error, "")
                self.assertEqual((self.calls, self.sends), (1, 1))
                self.assertEqual(len([s for s in self.sources if s.role == "assistant"]), 1)
                self.assertEqual(len(self.projections), 2)
                self.assertEqual(len(self.episodes), 1)
                self.assertEqual(self.store.get("s1").unread_count, 0)

    async def test_state_failure_after_send_preserves_new_messages_on_retry(self):
        original = self.store.put
        async def send(*args):
            self.sends += 1
            self.store.put = lambda state: (_ for _ in ()).throw(OSError("state busy"))
            return True
        self.runtime.message_sender.send = send
        result = await self.runtime.dispatch_deferred(self.context)
        self.assertTrue(result.delivered)
        self.assertEqual(result.error, "writeback_pending")
        self.assertEqual(self.store.get("s1").read_through_seq, 0)
        self.store.put = original
        self.now = 110
        newer = self.runtime.accept_user(RuntimeInput("s1", "new", event_time=110), event_id="u2")
        self.runtime.retry_writebacks()
        state = self.store.get("s1")
        self.assertEqual(state.read_through_seq, self.receipt.read_through_seq)
        self.assertEqual(state.last_unread_seq, newer.read_through_seq)
        self.assertEqual(state.unread_count, 1)
        self.assertEqual(state.wait_until, 115)
        self.assertEqual((self.calls, self.sends), (1, 1))

    async def test_disabled_worker_retries_only_writes(self):
        self.fail = "audit"
        await self.runtime.dispatch_deferred(self.context)
        self.fail = ""
        self.assertEqual(await self.worker().tick(), 0)
        self.assertEqual(len(self.episodes), 1)
        self.assertEqual((self.calls, self.sends), (1, 1))

    async def test_worker_stop_retries_pending_writes(self):
        self.fail = "source"
        await self.runtime.dispatch_deferred(self.context)
        worker = self.worker()
        task = asyncio.create_task(worker.run_forever())
        await asyncio.sleep(0)
        self.fail = ""
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(len(self.episodes), 1)
        self.assertEqual((self.calls, self.sends), (1, 1))

    async def test_sender_false_is_not_confirmed_delivery(self):
        async def send(*args):
            self.sends += 1
            return False
        self.runtime.message_sender.send = send
        result = await self.runtime.dispatch_deferred(self.context)
        self.assertFalse(result.delivered)
        self.assertEqual(result.error, "RuntimeError")
        self.assertGreater(self.store.get("s1").next_retry_at, self.now)
        self.assertEqual(len([s for s in self.sources if s.role == "assistant"]), 0)

    async def test_normal_delivery_audit_failure_still_acknowledges_and_retries(self):
        self.fail = "audit"
        self.runtime.record_delivery(
            run_id="normal", session_id="s1", decision="reply", reason="direct",
            read_through_seq=self.receipt.read_through_seq, now=106,
        )
        self.assertEqual(self.store.get("s1").unread_count, 0)
        self.now = 110
        self.runtime.accept_user(RuntimeInput("s1", "new", event_time=110), event_id="u2")
        self.fail = ""
        self.runtime.retry_writebacks()
        self.assertEqual(self.store.get("s1").unread_count, 1)
        self.assertEqual(len(self.episodes), 1)
        self.assertTrue(self.episodes[0].delivered)
        self.assertEqual((self.calls, self.sends), (0, 0))

    async def test_proactive_writeback_failure_keeps_new_schedule(self):
        self.runtime.schedule_proactive("s1", 0, now=105)
        async def send(*args):
            self.sends += 1
            self.now = 110
            self.runtime.accept_user(RuntimeInput("s1", "new", event_time=110), event_id="u2")
            self.runtime.schedule_proactive("s1", 20, now=110)
            return True
        self.runtime.message_sender.send = send
        self.fail = "audit"
        result = await self.runtime.dispatch_proactive(
            self.context, ProactiveDecision(True, "due"),
        )
        self.assertTrue(result.delivered)
        self.assertEqual(result.error, "writeback_pending")
        self.fail = ""
        self.runtime.retry_writebacks()
        self.assertEqual(self.store.get("s1").proactive_due_at, 130)
        self.assertEqual((self.calls, self.sends), (1, 1))

    async def test_trace_failure_does_not_hide_delivery_or_retry(self):
        self.runtime.trace = SimpleNamespace(record=lambda *a, **k: (_ for _ in ()).throw(OSError()))
        result = await self.runtime.dispatch_deferred(self.context)
        self.assertTrue(result.delivered)
        self.assertEqual(result.error, "")


class StorageFailureTest(unittest.TestCase):
    def test_json_replace_failure_preserves_disk_and_loaded_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = JsonStateStore(str(path))
            store.put(SessionState("s1", unread_count=1))
            before = path.read_bytes()
            with patch("app.runtime.state.os.replace", side_effect=OSError("busy")):
                with self.assertRaises(OSError):
                    store.put(SessionState("s1", unread_count=9))
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(store.get("s1").unread_count, 1)
            self.assertEqual(JsonStateStore(str(path)).get("s1").unread_count, 1)
            store.put(SessionState("s1", unread_count=9))
            self.assertEqual(store.last_error, "")

    def test_episode_retry_after_write_then_exception_uses_same_id(self):
        db = open_store(":memory:")
        self.addCleanup(db.close)
        original = db.runtime_episodes.append
        def append(payload):
            original(payload)
            raise OSError("acknowledgment lost")
        episode = EpisodeRecord("s1", "t", "reply", "direct", "reply", True, run_id="r1")
        sink = RepoEpisodeStore(db.runtime_episodes)
        with patch.object(db.runtime_episodes, "append", side_effect=append):
            with self.assertRaises(OSError):
                sink.append(episode)
        sink.append(episode)
        self.assertEqual(len(db.runtime_episodes.list("s1")), 1)
        self.assertEqual(sink.last_error, "")

    def test_jsonl_failures_are_observable(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "not-a-directory"
            path.write_text("file", encoding="utf-8")
            sink = JsonlEpisodeStore(str(path / "runs.jsonl"))
            with self.assertRaises(OSError):
                sink.append(EpisodeRecord("s1", "t", "x", "y", "reply", True))
            self.assertTrue(sink.last_error)


if __name__ == "__main__":
    unittest.main()
