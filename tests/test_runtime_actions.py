"""Runtime action, episode, tool policy and LLM gate tests."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.astrbot.actions import AstrBotActionPort  # noqa: E402
from adapters.astrbot.runtime import AstrBotRuntimeAdapter  # noqa: E402
from app.runtime import (  # noqa: E402
    AgentRuntime,
    RepoEpisodeStore,
    RepoStateStore,
    EpisodeRecorder,
    InMemoryStateStore,
    JsonlEpisodeStore,
    EpisodeRecord,
    ToolPolicy,
    WakeAction,
    RunDecision,
)
from core.interaction_policy import InteractionGate  # noqa: E402
from store import open_store  # noqa: E402


class Context:
    def __init__(self) -> None:
        self.sent = []

    async def send_message(self, session, chain):
        self.sent.append((session, chain))


class Event:
    def __init__(self) -> None:
        self.extras = {}
        # AstrBot uses True to prohibit its default model request.
        self.call_llm = False

    def set_extra(self, key, value):
        self.extras[key] = value

    def get_extra(self, key, default=None):
        return self.extras.get(key, default)

    def should_call_llm(self, value):
        self.call_llm = value


class ActionTest(unittest.TestCase):
    def test_episode_ids_remain_unique_when_clock_does_not_advance(self):
        from unittest.mock import patch
        db = open_store(os.path.join(tempfile.mkdtemp(), "clock.db"))
        self.addCleanup(db.close)
        sink = RepoEpisodeStore(db.runtime_episodes)
        episode = EpisodeRecord("s", "2026-10-23T10:00:00", "observe", "ambient",
                                 "reply", True)
        with patch("time.time_ns", return_value=123):
            for _ in range(4):
                sink.append(episode)
        self.assertEqual(sink.last_error, "")
        self.assertEqual(len(db.runtime_episodes.list("s")), 4)

    def test_send(self) -> None:
        context = Context()
        actions = AstrBotActionPort(context, message_factory=lambda text: text)
        self.assertTrue(asyncio.run(actions.send("s1", "hello")))
        self.assertEqual(context.sent, [("s1", "hello")])

    def test_send_reports_host_false_as_failure(self) -> None:
        class Context:
            async def send_message(self, session, chain):
                return False

        actions = AstrBotActionPort(Context(), message_factory=lambda text: text)
        self.assertFalse(asyncio.run(actions.send("s1", "hello")))
        self.assertFalse(asyncio.run(actions.send("s1", "")))

    def test_llm_gate_is_opt_in(self) -> None:
        event = Event()
        decision = RunDecision(WakeAction.OBSERVE, "ambient")
        AstrBotRuntimeAdapter.apply_llm_gate(event, decision, False)
        self.assertFalse(event.call_llm)
        AstrBotRuntimeAdapter.apply_llm_gate(event, decision, True)
        self.assertTrue(event.call_llm)

    def test_llm_gate_honors_must_reply(self) -> None:
        event = Event()
        decision = RunDecision(WakeAction.WAIT, "deferred", must_reply=True)
        AstrBotRuntimeAdapter.apply_llm_gate(event, decision, True)
        self.assertFalse(event.call_llm)

    def test_llm_gate_honors_relationship_denial(self) -> None:
        event = Event()
        decision = RunDecision(
            WakeAction.REPLY,
            "direct",
            must_reply=True,
        )
        AstrBotRuntimeAdapter.bind_interaction(
            event, InteractionGate(enforced=True, allow_reply=False)
        )
        AstrBotRuntimeAdapter.apply_llm_gate(event, decision, True)
        self.assertTrue(event.call_llm)

    def test_relationship_denial_respects_disabled_base_gate(self) -> None:
        event = Event()
        decision = RunDecision(
            WakeAction.REPLY,
            "relationship_low_group_ambient",
        )
        AstrBotRuntimeAdapter.bind_interaction(
            event, InteractionGate(enforced=True, allow_reply=False)
        )
        AstrBotRuntimeAdapter.apply_llm_gate(event, decision, False)
        self.assertFalse(event.call_llm)

    def test_tool_policy_and_trace(self) -> None:
        event = Event()
        policy = ToolPolicy(("memory_",))
        call = AstrBotRuntimeAdapter.observe_tool(
            event, "memory_search", {"query": "x"}, policy
        )
        self.assertTrue(call.allowed)
        self.assertEqual(event.extras["_seekmemory_tool_calls"], ("memory_search",))
        blocked = AstrBotRuntimeAdapter.observe_tool(event, "shell", {}, policy)
        self.assertFalse(blocked.allowed)

    def test_db_state_and_episode_stores(self) -> None:
        db = open_store(os.path.join(tempfile.mkdtemp(prefix="seekmem_runtime_db_"), "memory.db"))
        state_store = RepoStateStore(db.runtime_state)
        state = state_store.get("s1")
        state.quiet_until = 321
        state_store.put(state)
        loaded = RepoStateStore(db.runtime_state).get("s1")
        self.assertEqual(loaded.quiet_until, 321)
        state.last_event_at = 11.0
        state.proactive_due_at = 22.0
        state.proactive_attempts = 2
        state.followup_by_speaker = {"u1": 3}
        state_store.put(state)
        loaded = RepoStateStore(db.runtime_state).get("s1")
        self.assertEqual(loaded.last_event_at, 11.0)
        self.assertEqual(loaded.proactive_due_at, 22.0)
        self.assertEqual(loaded.proactive_attempts, 2)
        self.assertEqual(loaded.followup_by_speaker, {"u1": 3})
        self.assertEqual(db.runtime_state.sessions(), ["s1"])

        recorder = EpisodeRecorder(RepoEpisodeStore(db.runtime_episodes))
        recorder.record(EpisodeRecord(
            session_id="s1", at="2026-01-01T00:00:00", decision="reply",
            reason="mention", action="reply", delivered=True,
            response_chars=4, tool_calls=("memory_search",), outcome="ok",
            user_source_id="u1", assistant_source_id="a1",
        ))
        rows = db.runtime_episodes.list("s1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["decision"], "reply")
        self.assertIn("memory_search", rows[0]["tool_calls"])

    def test_db_pruning_and_storage_failures_are_observable(self) -> None:
        db = open_store(os.path.join(tempfile.mkdtemp(prefix="seekmem_runtime_prune_"), "memory.db"))
        recorder = EpisodeRecorder(RepoEpisodeStore(db.runtime_episodes))
        for i in range(3):
            recorder.record(EpisodeRecord(
                session_id="s1", at=f"2026-01-0{i + 1}T00:00:00",
                decision="observe", reason="ambient", action="reply",
                delivered=True, outcome="ok",
            ))
        self.assertGreaterEqual(db.runtime_episodes.prune(retention_days=0, max_rows=2), 1)
        self.assertEqual(len(db.runtime_episodes.list("s1")), 2)

        class BrokenState:
            def get(self, session_id):
                raise RuntimeError("busy")

            def put(self, session_id, payload):
                raise RuntimeError("busy")

        class BrokenEpisodes:
            def append(self, payload):
                raise RuntimeError("busy")

        state_store = RepoStateStore(BrokenState())
        with self.assertRaises(RuntimeError):
            state_store.get("s1")
        from app.runtime import SessionState
        with self.assertRaises(RuntimeError):
            state_store.put(SessionState("s1"))
        self.assertEqual(state_store.last_error, "RuntimeError")
        episode_store = RepoEpisodeStore(BrokenEpisodes())
        with self.assertRaises(RuntimeError):
            episode_store.append(EpisodeRecord(session_id="s1", at="t", decision="x",
                                               reason="y", action="z", delivered=False))
        self.assertEqual(episode_store.last_error, "RuntimeError")

    def test_episode_jsonl_has_no_message_body(self) -> None:
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_episode_"), "episodes.jsonl")
        recorder = EpisodeRecorder(JsonlEpisodeStore(path))
        recorder.record(EpisodeRecord(
            session_id="s1", at="t", decision="reply", reason="mention",
            action="reply", delivered=True, response_chars=3, outcome="ok",
            user_source_id="u1", assistant_source_id="a1",
        ))
        with open(path, encoding="utf-8") as handle:
            row = json.loads(handle.read())
        self.assertNotIn("text", row)
        self.assertEqual(row["response_chars"], 3)


if __name__ == "__main__":
    unittest.main()
