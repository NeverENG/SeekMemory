"""Relationship V2 candidate extraction behavior."""
from __future__ import annotations
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts import DialogueTurn
from perceive.absorb import build_plan

class RelationshipExtractionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.turn = DialogueTurn(
            "bot:FriendMessage:u1",
            "u1",
            "user",
            "早安呀",
            "2026-10-26T08:00:00",
            "s1",
            "topic-1",
        )

    def _raw(self, **updates) -> str:
        item = {
            "level": "scene",
            "text": "对机器人友好问候",
            "about": "relation",
            "subject_kind": "speaker",
            "subject_id": "u1",
            "confidence": 0.95,
            "relationship_reason": "friendly_greeting",
            "relationship_strength": "mild",
            "relationship_actor_source_id": "s1",
            "evidence_source_ids": ["s1"],
        }
        item.update(updates)
        return json.dumps([item], ensure_ascii=False)

    def test_relationship_candidate_is_not_memory_artifact(self) -> None:
        plan = build_plan([self.turn], [self.turn], self._raw(), None, strict=True)
        self.assertEqual(plan.artifacts, ())
        self.assertEqual(len(plan.relationship_candidates), 1)
        candidate = plan.relationship_candidates[0]
        self.assertEqual(candidate.subject_id, "u1")
        self.assertEqual(candidate.primary_source_id, "s1")
        self.assertEqual(candidate.source_ids, ("s1",))

    def test_model_signal_is_rejected_and_missing_evidence_is_retryable(self) -> None:
        signaled = build_plan(
            [self.turn], [self.turn], self._raw(relationship_signal="positive"), None
        )
        missing = build_plan(
            [self.turn], [self.turn], self._raw(evidence_source_ids=[]), None
        )
        self.assertTrue(signaled.outcome.model_failed)
        self.assertTrue(missing.outcome.model_failed)

    def test_relationship_candidates_reject_mixed_speakers_and_dedupe(self) -> None:
        second = DialogueTurn(
            "bot:FriendMessage:u1", "other", "user", "鱼，你真蠢",
            "2026-10-26T08:00:00", "s2", "topic-1",
        )
        raw = json.dumps([{
            "about": "relation", "relationship_reason": "insult",
            "relationship_strength": "strong", "relationship_actor_source_id": "s1",
            "evidence_source_ids": ["s1", "s2"],
        }])
        wrong = build_plan([self.turn, second], [self.turn, second], raw, None)
        duplicate = build_plan(
            [self.turn], [self.turn], json.dumps(json.loads(self._raw()) * 2), None
        )
        self.assertTrue(wrong.outcome.retryable)
        self.assertEqual(wrong.relationship_candidates, ())
        self.assertEqual(len(duplicate.relationship_candidates), 1)


if __name__ == "__main__":
    unittest.main()
