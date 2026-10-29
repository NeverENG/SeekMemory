"""Exercise extraction, evidence persistence and relationship maintenance.

验证抽取、证据持久化及关系维护。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import asyncio
import json
import os
from unittest.mock import patch
from contextlib import contextmanager
from adapters.relationship_policy import RelationshipReader
from app.contracts import DialogueTurn
from core.artifact import Lineage, Strength, TimeSpan, content_of, make, validate
from core.relationship import RelationshipBand, RelationshipSnapshot
from core.relationship_rules import (
    ConversationScope,
    RelationshipObservation,
    RelationshipReason,
    RelationshipScoringPolicy,
    RelationshipStrength,
    plan_relationship_revision,
)
from core.source import Source
from maintain.relationship import consolidate_relationships
from perceive.absorb import build_plan
from perceive.relationship import observation_boundary, signal_of
from services.maintenance_service import MaintenanceService
from store import open_store
from store.cache import Cache
from relationship_support import relationship_payload, observation

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
            "evidence_source_ids": ["s1"],
        }
        item.update(updates)
        return json.dumps([item], ensure_ascii=False)

    def test_extraction_stamps_version_and_derives_signal(self) -> None:
        plan = build_plan([self.turn], [self.turn], self._raw(), None, strict=True)
        self.assertEqual(len(plan.artifacts), 1)
        art = plan.artifacts[0]
        self.assertEqual(art.header.lineage.sources, ("s1",))
        self.assertEqual(art.payload["relationship_policy_version"], "relationship-v1")
        self.assertNotIn("relationship_signal", art.payload)
        self.assertEqual(signal_of(art.payload), "positive")

    def test_model_signal_is_rejected_and_missing_evidence_is_retryable(self) -> None:
        signaled = build_plan(
            [self.turn], [self.turn], self._raw(relationship_signal="positive"), None
        )
        missing = build_plan(
            [self.turn], [self.turn], self._raw(evidence_source_ids=[]), None
        )
        self.assertTrue(signaled.outcome.model_failed)
        self.assertTrue(missing.outcome.model_failed)
        self.assertTrue(missing.outcome.retryable)

    def test_observation_boundary_uses_reason_and_exact_evidence(self) -> None:
        payload = {
            "relationship_reason": "friendly_greeting",
            "relationship_strength": "mild",
        }
        first = observation_boundary("private-u1", payload, ("s1",))
        replay = observation_boundary("private-u1", payload, ("s1",))
        independent = observation_boundary("private-u1", payload, ("s2",))
        self.assertEqual(first, replay)
        self.assertNotEqual(first, independent)


class RelationshipMaintenanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)

    def add_observation(
        self,
        source_id: str,
        *,
        reason: str = "friendly_greeting",
        strength: str = "mild",
        confidence: float = 0.95,
        subject: str = "u1",
        speaker: str | None = None,
        session: str = "bot:FriendMessage:u1",
        created: str = "2026-10-26T12:00:00",
        extra_source: Source | None = None,
        policy_version: str = "relationship-v1",
    ):
        source = Source(
            source_id,
            f"turn-{source_id}",
            session,
            speaker or subject,
            "user",
            "fixture text",
            created,
        )
        rows = [source]
        lineage_ids = [source_id]
        if extra_source is not None:
            rows.append(extra_source)
            lineage_ids.append(extra_source.id)
        self.db.sources.append_sources(rows)
        art = make(
            "memory",
            {
                "text": "有证据的关系观察",
                "level": "scene",
                "about": "relation",
                "relationship_reason": reason,
                "relationship_strength": strength,
                "relationship_policy_version": policy_version,
            },
            subject_id=subject,
            strength=Strength(confidence=confidence),
            lineage=Lineage(sources=tuple(lineage_ids)),
            time=TimeSpan(created=created),
        )
        self.db.artifacts.commit(
            art,
            expected_revision=0,
            op="create",
            source_ids=tuple(lineage_ids),
        )
        self.cache.put(art)
        return art

    def test_private_and_group_evidence_persist_effective_policy_snapshot(self) -> None:
        self.add_observation("private")
        consolidate_relationships(self.db.artifacts, self.db.sources, self.cache)
        private = RelationshipReader(self.cache).get("u1")
        self.assertAlmostEqual(private.affinity, 0.0875)
        stored = self.db.artifacts.get(private.artifact_id)
        self.assertEqual(stored.payload["policy"], relationship_payload()["policy"])

        db = open_store(":memory:")
        self.addCleanup(db.close)
        cache = Cache(db.artifacts)
        source = Source(
            "group", "turn-group", "bot:GroupMessage:g1", "u2", "user",
            "fixture", "2026-10-26T12:00:00",
        )
        db.sources.append_sources([source])
        art = make(
            "memory",
            {
                "text": "关系观察",
                "level": "scene",
                "about": "relation",
                "relationship_reason": "friendly_greeting",
                "relationship_strength": "mild",
                "relationship_policy_version": "relationship-v1",
            },
            subject_id="u2",
            strength=Strength(confidence=0.95),
            lineage=Lineage(sources=("group",)),
        )
        db.artifacts.commit(art, expected_revision=0, op="create", source_ids=("group",))
        cache.put(art)
        consolidate_relationships(db.artifacts, db.sources, cache)
        self.assertAlmostEqual(RelationshipReader(cache).get("u2").affinity, 0.04375)

    def test_same_cycle_cap_consumes_all_reviewed_but_counts_one(self) -> None:
        rows = [
            self.add_observation(f"s{i}", created=f"2026-10-26T12:00:0{i}")
            for i in range(3)
        ]
        self.assertEqual(
            consolidate_relationships(self.db.artifacts, self.db.sources, self.cache), 1
        )
        relation = RelationshipReader(self.cache).get("u1")
        stored = self.db.artifacts.get(relation.artifact_id)
        self.assertEqual(relation.evidence_count, 1)
        self.assertEqual(stored.header.lineage.derived_from, tuple(row.header.id for row in rows))
        self.assertEqual(stored.header.lineage.sources, ("s0",))
        self.assertEqual(
            consolidate_relationships(self.db.artifacts, self.db.sources, self.cache), 0
        )

    def test_invalid_evidence_does_not_publish_relationship(self) -> None:
        self.add_observation("bad-reason", reason="unknown")
        self.add_observation("bad-strength", strength="extreme")
        self.add_observation("low-confidence", confidence=0.59)
        self.add_observation("wrong-subject", speaker="u2")
        mixed = Source(
            "mixed-group", "turn-mixed", "bot:GroupMessage:g1", "u1", "user",
            "fixture", "2026-10-26T12:00:00",
        )
        self.add_observation("mixed-private", extra_source=mixed)
        missing = make(
            "memory",
            {
                "text": "missing source",
                "level": "scene",
                "about": "relation",
                "relationship_reason": "gratitude",
                "relationship_strength": "mild",
                "relationship_policy_version": "relationship-v1",
            },
            subject_id="u1",
            strength=Strength(confidence=0.95),
            lineage=Lineage(sources=("invented",)),
        )
        self.cache.put(missing)
        self.assertEqual(
            consolidate_relationships(self.db.artifacts, self.db.sources, self.cache), 0
        )
        self.assertEqual(self.cache.active("relationship"), [])

    def test_commit_failure_does_not_publish_cache_head(self) -> None:
        self.add_observation("s1")
        with patch.object(
            self.db.artifacts, "commit", side_effect=RuntimeError("commit failed")
        ):
            with self.assertRaises(RuntimeError):
                consolidate_relationships(
                    self.db.artifacts, self.db.sources, self.cache
                )
        self.assertEqual(self.cache.active("relationship"), [])

    def test_maintenance_modes_and_weight_clamping(self) -> None:
        self.add_observation("mode-source")

        class Journal:
            @contextmanager
            def span(self, *args, **kwargs):
                yield {}

            def record(self, *args, **kwargs):
                pass

        class Logger:
            def __init__(self):
                self.warnings = []

            def info(self, message):
                pass

            def warning(self, message):
                self.warnings.append(message)

        config = {
            "relationship_mode": "off",
            "relationship_private_weight": 2.0,
            "relationship_group_weight": -1.0,
        }
        logger = Logger()
        service = MaintenanceService(
            artifacts=self.db.artifacts,
            sources=self.db.sources,
            cache=self.cache,
            journal=Journal(),
            task_id=lambda: "task",
            logger=logger,
            config=lambda key, default: config.get(key, default),
        )
        off = asyncio.run(service.weekly())
        self.assertEqual(off["relationships"], 0)
        self.assertEqual(self.cache.active("relationship"), [])
        config["relationship_mode"] = "invalid"
        self.assertEqual(service._relationship_mode(), "observe")
        config["relationship_mode"] = "observe"
        policy = service._relationship_policy()
        self.assertEqual(policy.private_weight, 1.0)
        self.assertEqual(policy.group_weight, 0.0)
        self.assertEqual(policy.unknown_weight, 0.0)
        observed = asyncio.run(service.weekly())
        self.assertEqual(observed["relationships"], 1)
        self.assertTrue(logger.warnings)


if __name__ == "__main__":
    unittest.main()
