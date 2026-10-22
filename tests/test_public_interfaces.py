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
    ArtifactStore,
    ChatModel,
    ExtractionStore,
    Retriever,
    SourceStore,
    StateStore,
)
from core.retrieval import RetrievalCandidate
from perceive.model import ProviderChatModel
from recall.retriever import HybridRetriever
from store.cache import Cache
from store.db import DB

class ProtocolSurfaceTest(unittest.TestCase):
    def setUp(self):
        self.db = DB(":memory:")
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db)

    def test_builtin_stores_satisfy_public_protocols(self):
        self.assertIsInstance(self.db, SourceStore)
        self.assertIsInstance(self.db, ArtifactStore)
        self.assertIsInstance(self.db, StateStore)
        self.assertIsInstance(self.db, ExtractionStore)

    def test_builtin_retriever_and_chat_model_satisfy_public_protocols(self):
        self.assertIsInstance(HybridRetriever(self.cache, self.cache), Retriever)
        self.assertIsInstance(ProviderChatModel(object()), ChatModel)

    def test_commit_surface_keeps_cas_and_state_events(self):
        names = inspect.signature(self.db.commit).parameters
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

    def test_dialogue_turn_optional_fields(self):
        turn = DialogueTurn("umo", "speaker", "user", "hello")
        self.assertEqual(turn.at, "")
        self.assertEqual(turn.source_id, "")
        self.assertEqual(turn.topic_id, "")

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
