from __future__ import annotations

import dataclasses
import inspect
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.contracts import (
    ChatRequest,
    ChatResponse,
    DialogueTurn,
    ExtractionState,
    RecallRequest,
    RecallResult,
    WriteOutcome,
)
from app.ports import (
    ArtifactCache,
    ArtifactStore,
    ChatModel,
    ExtractionStore,
    HistoryReader,
    LedgerStore,
    MetricsStore,
    Retriever,
    SourceStore,
)
from core.retrieval import RetrievalCandidate
from adapters.chatlab import ChatLabReader
from perceive.model import ProviderChatModel
from recall.retriever import HybridRetriever
from store.cache import Cache
from store import open_store

class ProtocolSurfaceTest(unittest.TestCase):
    def setUp(self):
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)

    def test_builtin_stores_satisfy_public_protocols(self):
        self.assertIsInstance(self.cache, ArtifactCache)
        self.assertIsInstance(self.db.sources, SourceStore)
        self.assertIsInstance(self.db.artifacts, ArtifactStore)
        self.assertIsInstance(self.db.extraction, ExtractionStore)
        self.assertIsInstance(self.db.metrics, MetricsStore)
        self.assertIsInstance(self.db.ledger, LedgerStore)
        self.assertTrue(callable(self.db.sources.recent_sources))
        self.assertTrue(callable(self.db.artifacts.by_source_ids))

    def test_builtin_retriever_and_chat_model_satisfy_public_protocols(self):
        self.assertIsInstance(HybridRetriever(self.cache, self.cache), Retriever)
        self.assertIsInstance(ProviderChatModel(object()), ChatModel)
        self.assertIsInstance(ChatLabReader(), HistoryReader)

    def test_commit_surface_keeps_cas_and_state_events(self):
        names = inspect.signature(self.db.artifacts.commit).parameters
        self.assertIn("expected_revision", names)
        self.assertIn("source_ids", names)
        self.assertIn("state_events", names)


class ContractDataclassTest(unittest.TestCase):
    def test_chat_request_defaults(self):
        req = ChatRequest("s", "system", "prompt")
        self.assertEqual(req.max_tokens, 800)
        self.assertEqual(req.temperature, 0.0)
        self.assertFalse(req.json_mode)

    def test_chat_response_defaults(self):
        resp = ChatResponse("text")
        self.assertEqual(resp.model, "")
        self.assertEqual(resp.usage_in, 0)
        self.assertEqual(resp.latency_ms, 0)

    def test_write_outcome_defaults(self):
        out = WriteOutcome()
        self.assertEqual(out.written, 0)
        self.assertEqual(out.errors, ())
        self.assertFalse(out.model_failed)
        self.assertEqual(out.usage_in, 0)
        self.assertEqual(out.usage_cached, 0)
        self.assertEqual(out.usage_out, 0)

    def test_dialogue_turn_optional_fields(self):
        turn = DialogueTurn("umo", "speaker", "user", "hello")
        self.assertEqual(turn.at, "")
        self.assertEqual(turn.source_id, "")
        self.assertEqual(turn.topic_id, "")
        self.assertEqual(turn.turn_id, "")
        self.assertIsNone(turn.reply_to)

    def test_dialogue_turn_trailing_pair_fields(self):
        turn = DialogueTurn("umo", "bot", "assistant", "reply", "", "s_a",
                            "tp", "t1", "s_u")
        self.assertEqual(turn.turn_id, "t1")
        self.assertEqual(turn.reply_to, "s_u")
        self.assertEqual(
            turn,
            DialogueTurn("umo", "bot", "assistant", "reply", source_id="s_a",
                         topic_id="tp", turn_id="t1", reply_to="s_u"),
        )

    def test_extraction_state_defaults(self):
        state = ExtractionState("source", "turn", "session")
        self.assertEqual(state.topic_id, "")
        self.assertEqual(state.state, "pending")
        self.assertEqual(state.attempts, 0)
        self.assertEqual(state.last_error, "")

    def test_retrieval_candidate_defaults(self):
        art = object()
        candidate = RetrievalCandidate(art)
        self.assertIs(candidate.artifact, art)
        self.assertEqual(candidate.activation, 0.0)
        self.assertEqual(candidate.lexical, 0.0)

    def test_recall_dto_defaults(self):
        req = RecallRequest("query", "session")
        result = RecallResult()
        self.assertEqual(req.present_ids, ())
        self.assertEqual(result.mode, "none")
        self.assertEqual(result.chars, 0)


if __name__ == "__main__":
    unittest.main()
