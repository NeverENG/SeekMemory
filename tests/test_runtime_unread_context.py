"""Source-backed, bounded context for runtime-owned deferred dispatch."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from dataclasses import replace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime import AgentRuntime, RunContext, RunRecorder, RuntimeInput, RuntimeWorker  # noqa: E402
from app.runtime.state import RepoStateStore  # noqa: E402
from app.runtime.scheduler import Scheduler  # noqa: E402
from store import open_store  # noqa: E402


class UnreadContextDispatchTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.db = open_store(":memory:")
        self.store = RepoStateStore(self.db.runtime_state)
        self.model_inputs: list[tuple[str, str, str | None]] = []
        self.sent: list[tuple[str, str]] = []
        self.traces: list[tuple] = []

        async def complete(session: str, prompt: str, system: str | None) -> str:
            self.model_inputs.append((session, prompt, system))
            return "回复"

        async def send(session: str, text: str) -> bool:
            self.sent.append((session, text))
            return True

        self.runtime = AgentRuntime(
            self.store, clock=lambda: self.now, wait_seconds=5,
            trace=SimpleNamespace(record=lambda *row: self.traces.append(row)),
            recorder=RunRecorder(sources=self.db.sources, buffer=None, checkpoint=None, episodes=None),
            model_gateway=SimpleNamespace(complete=complete),
            message_sender=SimpleNamespace(send=send),
            source_reader=self.db.sources, run_control_enabled=True,
        )
        self.now = 100.0

    async def asyncTearDown(self) -> None:
        self.db.close()

    def accept(self, lane: str, event_id: str, text: str, *, speaker: str = "person"):
        return self.runtime.accept_user(RuntimeInput(
            lane, text, event_id=event_id, speaker_id=speaker, event_time=self.now,
        ), now=self.now)

    async def test_superseded_input_is_included_once_with_new_input(self) -> None:
        first = self.accept("s1", "old", "第一条")
        self.now = 101.0
        second = self.accept("s1", "new", "第二条")
        self.now = 106.0
        result = await self.runtime.dispatch_deferred(
            RunContext("s1", "第一条", source_id=first.source_id), now=self.now,
        )
        self.assertTrue(result.delivered)
        self.assertEqual(len(self.model_inputs), 1)
        session, prompt, _ = self.model_inputs[0]
        self.assertEqual(session, "s1")
        self.assertEqual(prompt.count("第一条"), 1)
        self.assertEqual(prompt.count("第二条"), 1)
        self.assertEqual(prompt.count("发言者1"), 2)
        self.assertLess(prompt.index("第一条"), prompt.index("第二条"))
        self.assertEqual(self.store.get("s1").unread_sources, {})
        self.assertEqual(self.store.get("s1").read_through_seq, second.read_through_seq)
        self.assertEqual(len(self.sent), 1)
        self.assertIn(first.source_id, self.db.sources.sources_by_ids([first.source_id]))
        replies = [source for source in self.db.sources.recent_sources(since="", limit=10)
                   if source.role == "assistant"]
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0].reply_to, second.source_id)

    async def test_group_speakers_are_distinct_without_exposing_identifiers(self) -> None:
        self.accept("s1", "a", "你好", speaker="private-speaker-A")
        self.now = 101.0
        self.accept("s1", "b", "再见", speaker="private-speaker-B")
        self.now = 106.0
        result = await self.runtime.dispatch_deferred(RunContext("s1", "再见"), now=self.now)
        self.assertTrue(result.delivered)
        prompt = self.model_inputs[0][1]
        self.assertIn("发言者1", prompt)
        self.assertIn("发言者2", prompt)
        self.assertNotIn("private-speaker", prompt)

    async def test_old_delivery_only_leaves_new_input_for_next_model(self) -> None:
        first = self.accept("s1", "a", "旧消息")
        self.now = 101.0
        second = self.accept("s1", "b", "新消息")
        self.runtime.record_delivery(
            run_id="old", session_id="s1", decision="reply", reason="direct_attention",
            read_through_seq=first.read_through_seq, now=102.0,
        )
        self.now = 106.0
        result = await self.runtime.dispatch_deferred(
            RunContext("s1", "旧消息", source_id=first.source_id), now=self.now,
        )
        self.assertTrue(result.delivered)
        self.assertEqual(self.model_inputs[0][1], "新消息")
        self.assertEqual(self.store.get("s1").read_through_seq, second.read_through_seq)

    async def test_other_lane_is_not_part_of_context(self) -> None:
        self.accept("s1", "a", "第一会话")
        self.accept("s2", "secret", "其他会话的私密输入")
        self.now = 105.0
        result = await self.runtime.dispatch_deferred(RunContext("s1", "第一会话"), now=self.now)
        self.assertTrue(result.delivered)
        self.assertEqual(self.model_inputs[0][1], "第一会话")
        self.assertEqual(self.store.get("s2").unread_count, 1)

    async def test_wrong_lane_source_does_not_consume_unread(self) -> None:
        first = self.accept("s1", "a", "第一条")
        # Reader returns the wrong lane for an otherwise valid Source ID.
        original = self.runtime.source_reader
        source = self.db.sources.sources_by_ids([first.source_id])[first.source_id]
        self.runtime.source_reader = SimpleNamespace(sources_by_ids=lambda _: {
            first.source_id: replace(source, session_id="s2"),
        })
        self.now = 105.0
        result = await self.runtime.dispatch_deferred(RunContext("s1", "第一条"), now=self.now)
        self.assertFalse(result.delivered)
        self.assertEqual(self.model_inputs, [])
        self.assertEqual(self.sent, [])
        self.assertEqual(self.store.get("s1").unread_count, 1)
        self.assertEqual(result.error, "unread_context_unavailable")
        self.assertIn(("runtime", "unread_context_unavailable", {"unread": 1}), self.traces)
        self.assertNotIn("第一条", str(self.traces))
        self.runtime.source_reader = original

    async def test_missing_source_does_not_send_partial_context(self) -> None:
        self.accept("s1", "a", "第一条")
        self.now = 101.0
        self.accept("s1", "b", "第二条")
        self.runtime.source_reader = SimpleNamespace(sources_by_ids=lambda _: {})
        self.now = 106.0
        result = await self.runtime.dispatch_deferred(RunContext("s1", "第二条"), now=self.now)
        self.assertEqual(result.error, "unread_context_unavailable")
        self.assertEqual(self.model_inputs, [])
        self.assertEqual(self.sent, [])
        self.assertEqual(self.store.get("s1").read_through_seq, 0)
        self.assertEqual(self.store.get("s1").unread_count, 2)

    async def test_reader_failure_does_not_leak_content_or_acknowledge(self) -> None:
        self.accept("s1", "a", "私人消息")

        def fail(_):
            raise OSError("private-reader-detail")

        self.runtime.source_reader = SimpleNamespace(sources_by_ids=fail)
        self.now = 105.0
        result = await self.runtime.dispatch_deferred(RunContext("s1", "私人消息"), now=self.now)
        self.assertEqual(result.error, "unread_context_unavailable")
        self.assertEqual(self.model_inputs, [])
        self.assertEqual(self.store.get("s1").read_through_seq, 0)
        self.assertNotIn("private-reader-detail", str(self.traces))
        self.assertNotIn("私人消息", str(self.traces))

    async def test_over_32_messages_are_delivered_in_order_without_early_ack(self) -> None:
        accepted = [self.accept("s1", str(i), f"消息{i}") for i in range(33)]
        self.now = 105.0
        context = RunContext("s1", "消息32", source_id=accepted[-1].source_id)
        first = await self.runtime.dispatch_deferred(context, now=self.now)
        self.assertTrue(first.delivered)
        self.assertEqual(len(self.model_inputs), 1)
        self.assertIn("消息0", self.model_inputs[0][1])
        self.assertIn("消息31", self.model_inputs[0][1])
        self.assertNotIn('"消息32"', self.model_inputs[0][1])
        state = self.store.get("s1")
        self.assertEqual(state.read_through_seq, accepted[31].read_through_seq)
        self.assertEqual(state.unread_sources, {str(accepted[32].read_through_seq): accepted[32].source_id})
        self.assertEqual(state.unread_count, 1)
        self.assertTrue(Scheduler(self.store).due(["s1"], self.now))
        replies = [source for source in self.db.sources.recent_sources(since="", limit=100)
                   if source.role == "assistant"]
        self.assertEqual(replies[0].reply_to, accepted[31].source_id)

        second = await self.runtime.dispatch_deferred(context, now=self.now)
        self.assertTrue(second.delivered)
        self.assertEqual(self.model_inputs[1][1], "消息32")
        self.assertEqual(self.store.get("s1").read_through_seq, accepted[32].read_through_seq)
        self.assertEqual(self.store.get("s1").unread_sources, {})
        self.assertFalse(Scheduler(self.store).due(["s1"], self.now))
        replies = [source for source in self.db.sources.recent_sources(since="", limit=100)
                   if source.role == "assistant"]
        self.assertEqual({source.reply_to for source in replies},
                         {accepted[31].source_id, accepted[32].source_id})

    async def test_worker_tick_supersedes_unsent_reply_and_recovers_both_sources(self) -> None:
        first = self.accept("s1", "old", "旧消息")
        started, release = asyncio.Event(), asyncio.Event()
        prompts: list[str] = []

        async def complete(_session: str, prompt: str, _system: str | None) -> str:
            prompts.append(prompt)
            if len(prompts) == 1:
                started.set()
                await release.wait()
                return "过期回复"
            return "新回复"

        self.runtime.model_gateway = SimpleNamespace(complete=complete)
        worker = RuntimeWorker(
            runtime=self.runtime, scheduler=Scheduler(self.store),
            enabled=lambda: True, session_ids=lambda _: ["s1"],
            run_context=lambda lane, moment: RunContext(
                lane, str(self.db.sources.latest_user_source(lane)["text"]),
                source_id=str(self.db.sources.latest_user_source(lane)["id"]),
                received_at=moment,
            ),
            interval_seconds=lambda: 1, max_attempts=lambda: 3,
            base_seconds=lambda: 2, clock=lambda: self.now,
        )
        self.now = 105.0
        old_tick = asyncio.create_task(worker.tick(now=self.now))
        await asyncio.wait_for(started.wait(), 1)
        self.now = 106.0
        second = self.accept("s1", "new", "新消息")
        release.set()
        await asyncio.wait_for(old_tick, 1)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.store.get("s1").read_through_seq, 0)
        self.assertEqual(self.store.get("s1").wait_until, 111.0)
        self.assertEqual(self.store.get("s1").unread_count, 2)

        self.now = 111.0
        self.assertEqual(await worker.tick(now=self.now), 1)
        self.assertEqual(self.sent, [("s1", "新回复")])
        self.assertEqual(len(prompts), 2)
        self.assertEqual(prompts[1].count("旧消息"), 1)
        self.assertEqual(prompts[1].count("新消息"), 1)
        state = self.store.get("s1")
        self.assertEqual(state.read_through_seq, second.read_through_seq)
        self.assertEqual(state.unread_sources, {})
        self.assertEqual(state.next_retry_at, 0.0)
        self.assertIn(first.source_id, self.db.sources.sources_by_ids([first.source_id]))
        replies = [source for source in self.db.sources.recent_sources(since="", limit=10)
                   if source.role == "assistant"]
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0].reply_to, second.source_id)

    async def test_worker_ticks_continue_remaining_batch_after_state_reload(self) -> None:
        accepted = [self.accept("s1", str(i), f"消息{i}") for i in range(33)]
        self.now = 105.0

        def worker(runtime: AgentRuntime) -> RuntimeWorker:
            return RuntimeWorker(
                runtime=runtime, scheduler=Scheduler(runtime.store),
                enabled=lambda: True, session_ids=lambda _: self.db.runtime_state.sessions(),
                run_context=lambda lane, moment: RunContext(
                    lane, str(self.db.sources.latest_user_source(lane)["text"]),
                    source_id=str(self.db.sources.latest_user_source(lane)["id"]),
                    received_at=moment,
                ),
                interval_seconds=lambda: 1, max_attempts=lambda: 3,
                base_seconds=lambda: 2, clock=lambda: self.now,
            )

        self.assertEqual(await worker(self.runtime).tick(now=self.now), 1)
        self.assertEqual(self.store.get("s1").read_through_seq, accepted[31].read_through_seq)
        reloaded = AgentRuntime(
            RepoStateStore(self.db.runtime_state), clock=lambda: self.now, wait_seconds=5,
            recorder=RunRecorder(sources=self.db.sources, buffer=None, checkpoint=None, episodes=None),
            model_gateway=self.runtime.model_gateway, message_sender=self.runtime.message_sender,
            source_reader=self.db.sources, run_control_enabled=True,
        )
        self.now = 106.0
        self.assertEqual(await worker(reloaded).tick(now=self.now), 1)
        self.assertEqual(self.model_inputs[-1][1], "消息32")
        self.assertEqual(self.store.get("s1").read_through_seq, accepted[32].read_through_seq)
        self.assertEqual(await worker(reloaded).tick(now=self.now), 0)
        self.assertEqual(len(self.sent), 2)

    async def test_missing_later_mapping_blocks_later_batch_not_valid_prefix(self) -> None:
        accepted = [self.accept("s1", str(i), f"消息{i}") for i in range(33)]
        state = self.store.get("s1")
        state.unread_sources.pop(str(accepted[32].read_through_seq))
        self.store.put(state)
        self.now = 105.0
        context = RunContext("s1", "消息32")
        first = await self.runtime.dispatch_deferred(context, now=self.now)
        self.assertTrue(first.delivered)
        self.assertEqual(self.store.get("s1").read_through_seq, accepted[31].read_through_seq)
        second = await self.runtime.dispatch_deferred(context, now=self.now)
        self.assertEqual(second.error, "unread_context_unavailable")
        self.assertEqual(self.store.get("s1").unread_count, 1)
        self.assertEqual(len(self.sent), 1)

    async def test_partial_delivery_state_failure_preserves_new_input_on_writeback(self) -> None:
        accepted = [self.accept("s1", str(i), f"消息{i}") for i in range(33)]
        self.now = 105.0
        context = RunContext("s1", "消息32")
        original_put = self.store.put
        original_send = self.runtime.message_sender.send

        async def fail_state_after_send(session: str, text: str) -> bool:
            delivered = await original_send(session, text)
            self.store.put = lambda _: (_ for _ in ()).throw(OSError("state busy"))
            return delivered

        self.runtime.message_sender.send = fail_state_after_send
        first = await self.runtime.dispatch_deferred(context, now=self.now)
        self.assertTrue(first.delivered)
        self.assertEqual(first.error, "writeback_pending")
        self.assertEqual(self.store.get("s1").read_through_seq, 0)
        pending = await self.runtime.dispatch_deferred(context, now=self.now)
        self.assertEqual(pending.error, "writeback_pending")
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(len(self.model_inputs), 1)

        self.store.put = original_put
        self.runtime.message_sender.send = original_send
        self.now = 106.0
        newer = self.accept("s1", "new", "新消息")
        self.assertEqual(self.runtime.retry_writebacks(), 1)
        state = self.store.get("s1")
        self.assertEqual(state.read_through_seq, accepted[31].read_through_seq)
        self.assertEqual(state.last_unread_seq, newer.read_through_seq)
        self.assertEqual(state.unread_count, 2)
        self.assertEqual(state.wait_until, 111.0)
        self.now = 111.0
        second = await self.runtime.dispatch_deferred(context, now=self.now)
        self.assertTrue(second.delivered)
        self.assertIn("消息32", self.model_inputs[1][1])
        self.assertIn("新消息", self.model_inputs[1][1])
        self.assertNotIn('"消息31"', self.model_inputs[1][1])
        self.assertEqual(self.store.get("s1").read_through_seq, newer.read_through_seq)
        self.assertEqual(len(self.sent), 2)

    async def test_utf8_budget_splits_without_truncating_messages(self) -> None:
        first_text, second_text = "甲" * 3000, "乙" * 3000
        first = self.accept("s1", "a", first_text)
        second = self.accept("s1", "b", second_text)
        self.now = 105.0
        self.assertTrue((await self.runtime.dispatch_deferred(
            RunContext("s1", second_text, source_id=second.source_id), now=self.now,
        )).delivered)
        self.assertEqual(self.model_inputs[0][1], first_text)
        self.assertEqual(self.store.get("s1").read_through_seq, first.read_through_seq)
        self.assertTrue((await self.runtime.dispatch_deferred(
            RunContext("s1", first_text, source_id=first.source_id), now=self.now,
        )).delivered)
        self.assertEqual(self.model_inputs[1][1], second_text)
        self.assertEqual(self.store.get("s1").read_through_seq, second.read_through_seq)

    async def test_missing_next_batch_blocks_without_acknowledging_it(self) -> None:
        accepted = [self.accept("s1", str(i), f"消息{i}") for i in range(33)]
        self.now = 105.0
        self.assertTrue((await self.runtime.dispatch_deferred(
            RunContext("s1", "消息32"), now=self.now,
        )).delivered)
        self.runtime.source_reader = SimpleNamespace(sources_by_ids=lambda _: {})
        result = await self.runtime.dispatch_deferred(RunContext("s1", "消息32"), now=self.now)
        self.assertEqual(result.error, "unread_context_unavailable")
        self.assertEqual(len(self.model_inputs), 1)
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.store.get("s1").read_through_seq, accepted[31].read_through_seq)
        self.assertEqual(self.store.get("s1").unread_count, 1)

    async def test_failed_remaining_batch_retries_without_replaying_delivered_batch(self) -> None:
        accepted = [self.accept("s1", str(i), f"消息{i}") for i in range(33)]
        self.now = 105.0
        context = RunContext("s1", "消息32", source_id=accepted[-1].source_id)
        self.assertTrue((await self.runtime.dispatch_deferred(context, now=self.now)).delivered)

        async def fail_model(_session: str, _prompt: str, _system: str | None) -> str:
            raise RuntimeError("model_failed")

        original = self.runtime.model_gateway
        self.runtime.model_gateway = SimpleNamespace(complete=fail_model)
        failed = await self.runtime.dispatch_deferred(context, now=self.now)
        self.assertEqual(failed.error, "RuntimeError")
        self.assertEqual(self.store.get("s1").read_through_seq, accepted[31].read_through_seq)
        self.assertEqual(len(self.sent), 1)
        self.assertFalse(Scheduler(self.store).due(["s1"], 106.0))
        self.runtime.model_gateway = original
        self.now = 107.0
        self.assertTrue((await self.runtime.dispatch_deferred(context, now=self.now)).delivered)
        self.assertEqual(self.model_inputs[-1][1], "消息32")
        self.assertEqual(self.store.get("s1").read_through_seq, accepted[32].read_through_seq)

    async def test_new_input_supersedes_unfinished_batch_without_acknowledgement(self) -> None:
        self.accept("s1", "a", "甲" * 3000)
        self.accept("s1", "b", "乙" * 3000)
        started, release = asyncio.Event(), asyncio.Event()

        async def slow_model(_session: str, _prompt: str, _system: str | None) -> str:
            started.set()
            await release.wait()
            return "过期回复"

        self.runtime.model_gateway = SimpleNamespace(complete=slow_model)
        self.now = 105.0
        running = asyncio.create_task(self.runtime.dispatch_deferred(
            RunContext("s1", "乙" * 3000), now=self.now,
        ))
        await asyncio.wait_for(started.wait(), 1)
        self.now = 106.0
        self.accept("s1", "new", "新消息")
        release.set()
        result = await running
        self.assertEqual(result.error, "superseded")
        self.assertEqual(self.sent, [])
        self.assertEqual(self.store.get("s1").read_through_seq, 0)
        self.assertEqual(self.store.get("s1").unread_count, 3)

    async def test_oversized_unread_input_is_not_partially_acknowledged(self) -> None:
        self.accept("s1", "a", "很长" * 4000)
        self.now = 105.0
        result = await self.runtime.dispatch_deferred(RunContext("s1", "最新"), now=self.now)
        self.assertFalse(result.delivered)
        self.assertEqual(self.model_inputs, [])
        self.assertEqual(self.store.get("s1").read_through_seq, 0)
        self.assertEqual(self.store.get("s1").unread_count, 1)
        self.assertEqual(result.error, "unread_context_unavailable")


if __name__ == "__main__":
    unittest.main()
