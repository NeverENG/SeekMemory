"""Verify read-only recall and explicit model-context recording.

验证只读召回及明确的模型上下文记录。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.astrbot.context import SeekMemoryContextAdapter
from app.budget import ContextBudget
from app.runtime import AgentRuntime, InMemoryStateStore, RunContext, RunRecorder
from app.runtime.contracts import MemoryContext, RuntimeInput, ProactiveDecision
from core.artifact import make
from core.graph import Graph
from recall.pipeline import build_block, query_block
from services.recall_service import RecallService
from store import open_store
from store.cache import Cache


class RecallContextTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.graph = Graph(self.db.artifacts)
        self.session = "bot:FriendMessage:u"
        self.art = make("designated", {"text": "给你保管的专属清单", "trigger": "清单", "owner_umo": self.session})
        self.db.artifacts.commit(self.art, expected_revision=0, op="create")
        self.cache.put(self.art)
        self.service = RecallService(
            cache=self.cache, graph=self.graph, artifacts=self.db.artifacts, sources=self.db.sources,
            budget=ContextBudget(injection_chars=600), config=lambda _key, default: default,
            owner_umo=lambda: self.session,
        )

    def args(self):
        return (self.cache, self.graph, self.db.artifacts, self.db.sources, self.session,
                "清单", True, lambda _key, default: default, self.session, "u")

    def test_new_queries_and_preview_never_commit(self):
        with patch.object(self.db.artifacts, "commit", side_effect=AssertionError("hidden write")):
            block, info = query_block(*self.args())
            second, _ = self.service.query("清单", self.session, True, "u")
            preview = self.service.preview("清单", self.session, True, "u")
        self.assertIn(self.art.payload["text"], block)
        self.assertEqual(second, block)
        self.assertEqual(preview["block"], block)
        self.assertEqual(info["designated_ids"], (self.art.header.id,))
        self.assertEqual(self.db.artifacts.get(self.art.header.id), self.art)

    def test_legacy_build_keeps_default_recording_behavior(self):
        block, _info = build_block(*self.args())
        self.assertIn(self.art.payload["text"], block)
        self.assertTrue(self.db.artifacts.get(self.art.header.id).payload.get("given"))

    def test_explicit_recording_is_repeatable_without_extra_revision(self):
        block, info = self.service.query("清单", self.session, True, "u")
        self.assertEqual(self.service.record_context_injection(block, info), 1)
        self.assertEqual(self.service.record_context_injection(block, info), 0)
        self.assertEqual(self.db.artifacts.get(self.art.header.id).header.revision, 2)
        self.assertEqual(len(self.db.ledger.entries()), 2)

    def test_budget_dropped_body_is_not_consumed(self):
        self.service.budget = ContextBudget(injection_chars=0)
        block, info = self.service.query("清单", self.session, True, "u")
        self.assertNotIn(self.art.payload["text"], block)
        self.assertEqual(self.service.record_context_injection(block, info), 0)
        self.assertEqual(self.db.artifacts.get(self.art.header.id), self.art)

    async def test_generic_runtime_records_before_model_failure_without_memory_semantics(self):
        context = MemoryContext("included text", {"final_ids": ("x",)})
        calls = []

        def record(actual):
            calls.append(("context", actual))

        async def model(*args):
            self.assertEqual(calls, [("context", context)])
            raise RuntimeError("model failed")

        adapter = SeekMemoryContextAdapter(lambda _request: context, record)
        runtime = AgentRuntime(
            InMemoryStateStore(), clock=lambda: 100, wait_seconds=1,
            memory_context=adapter, context_recorder=adapter,
            model_gateway=SimpleNamespace(complete=model),
            message_sender=SimpleNamespace(send=None),
            recorder=RunRecorder(sources=None, buffer=None, checkpoint=None, episodes=None),
        )
        runtime.observe(RuntimeInput("s", "question"), now=100)
        result = await runtime.dispatch_deferred(RunContext("s", "question"), now=102)
        self.assertFalse(result.delivered)
        self.assertEqual(calls, [("context", context)])

    async def test_proactive_context_is_recorded_before_send_failure(self):
        calls = []
        context = MemoryContext("included text", {})

        async def model(*args):
            self.assertEqual(calls, [context])
            return "reply"

        async def send(*args):
            self.assertEqual(calls, [context])
            raise OSError("send failed")

        adapter = SeekMemoryContextAdapter(lambda _request: context, calls.append)
        runtime = AgentRuntime(
            InMemoryStateStore(), clock=lambda: 100, memory_context=adapter, context_recorder=adapter,
            model_gateway=SimpleNamespace(complete=model), message_sender=SimpleNamespace(send=send),
            recorder=RunRecorder(sources=None, buffer=None, checkpoint=None, episodes=None),
        )
        result = await runtime.dispatch_proactive(RunContext("s", "question"),
                                                 ProactiveDecision(True, "due"), now=100)
        self.assertFalse(result.delivered)
        self.assertEqual(calls, [context])


if __name__ == "__main__":
    unittest.main()
