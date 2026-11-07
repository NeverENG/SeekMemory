"""Relationship V2 projection and snapshot behavior."""
from __future__ import annotations
import math
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.artifact import content_of, make, validate
from core.relationship import RelationshipSnapshot
from core.relationship_rules import (
    ConversationScope, RelationshipReason, RelationshipScoringPolicy,
    RelationshipStrength, VerifiedRelationshipEvent, project_relationship,
)

def relationship_payload(**updates):
    payload = {
        "summary": "关系状态：观察中", "familiarity": 0.0, "trust": 0.0,
        "warmth": 0.0, "tension": 0.0, "stability": 0.0, "confidence": 0.0,
        "evidence_count": 1, "last_evidence_at": "2026-10-26T00:00:00+00:00",
        "evaluated_at": "2026-10-26T00:00:00+00:00",
        "policy": {"version": "relationship-v2"},
    }
    payload.update(updates)
    return payload

class RelationshipCoreTest(unittest.TestCase):
    def test_relationship_artifact_requires_v2_dimensions(self) -> None:
        art = make("relationship", relationship_payload(), subject_id="u1")
        validate(art)
        self.assertEqual(content_of(art), "关系状态：观察中")
        with self.assertRaises(ValueError):
            validate(make("relationship", relationship_payload(warmth=2), subject_id="u1"))

    def test_projection_uses_only_supplied_verified_evidence(self) -> None:
        now = datetime(2026, 10, 26, tzinfo=timezone.utc)
        policy = RelationshipScoringPolicy()
        # Quoted or abstained candidates are not verified events passed by the caller.
        empty = project_relationship([], now, policy)
        self.assertEqual(empty, RelationshipSnapshot(evaluated_at=now.isoformat()))
        insult = VerifiedRelationshipEvent(
            "n", "u1", RelationshipReason.INSULT, RelationshipStrength.MILD,
            ConversationScope.PRIVATE, now, "s1", ("s1",),
        )
        negative = project_relationship([insult], now, policy)
        self.assertGreater(negative.tension, 0)
        self.assertLess(negative.trust, 0)
        self.assertLess(negative.warmth, 0)
        self.assertEqual(negative.evidence_count, 1)

    def test_dimensions_decay_at_explicit_clock_without_inventing_stability(self) -> None:
        now = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
        greeting = VerifiedRelationshipEvent(
            "g", "u1", RelationshipReason.FRIENDLY_GREETING, RelationshipStrength.MILD,
            ConversationScope.PRIVATE, now, "s1", ("s1",),
        )
        policy = RelationshipScoringPolicy()
        first = project_relationship([greeting], now, policy)
        later = project_relationship([greeting], now + timedelta(hours=12), policy)
        self.assertGreater(first.familiarity, 0)
        self.assertGreater(first.confidence, 0)
        self.assertGreater(first.warmth, later.warmth)
        self.assertGreater(first.familiarity, later.familiarity)
        halfway = project_relationship([greeting], now + timedelta(days=45), policy)
        self.assertAlmostEqual(2 * math.atanh(halfway.warmth), math.atanh(first.warmth), places=5)
        self.assertGreater(first.confidence, later.confidence)
        self.assertEqual((first.trust, first.tension, first.stability), (0, 0, 0))
        self.assertEqual(first.last_evidence_at, now.isoformat())
        self.assertEqual(later.evaluated_at, (now + timedelta(hours=12)).isoformat())
        self.assertEqual(first.evidence_count, later.evidence_count)
        expired = project_relationship(
            [greeting], now + timedelta(seconds=1),
            RelationshipScoringPolicy(warmth_half_life_days=0),
        )
        self.assertEqual(expired.warmth, 0)
        self.assertGreater(expired.familiarity, 0)

    def test_conflict_cools_after_cooldown_without_new_positive_evidence(self) -> None:
        now = datetime(2026, 10, 26, 12, tzinfo=timezone.utc)
        insult = VerifiedRelationshipEvent(
            "n", "u1", RelationshipReason.INSULT, RelationshipStrength.STRONG,
            ConversationScope.PRIVATE, now, "s1", ("s1",),
        )
        policy = RelationshipScoringPolicy()
        fresh = project_relationship([insult], now, policy)
        during_cooldown = project_relationship([insult], now + timedelta(hours=12), policy)
        cooled = project_relationship([insult], now + timedelta(days=15), policy)
        self.assertEqual(fresh.tension, during_cooldown.tension)
        self.assertGreater(during_cooldown.tension, cooled.tension)
        self.assertLess(fresh.trust, cooled.trust)
        self.assertLess(fresh.warmth, 0)

    def test_only_linked_later_repair_cools_its_negative_once(self) -> None:
        now = datetime(2026, 10, 26, tzinfo=timezone.utc)
        negative = VerifiedRelationshipEvent(
            "n", "u1", RelationshipReason.INSULT, RelationshipStrength.STRONG,
            ConversationScope.PRIVATE, now, "s1", ("s1",),
        )
        repair_at = now + timedelta(hours=2)
        def repair(event_id: str, source: str, link: str, at: datetime = repair_at) -> VerifiedRelationshipEvent:
            return VerifiedRelationshipEvent(
                event_id, "u1", RelationshipReason.REPAIR, RelationshipStrength.MILD,
                ConversationScope.PRIVATE, at, source, (source,), link,
            )
        policy = RelationshipScoringPolicy()
        clock = repair_at + timedelta(hours=1)
        baseline = project_relationship([negative], clock, policy)
        linked = project_relationship([negative, repair("r1", "s2", "n")], clock, policy)
        context = project_relationship([
            negative,
            VerifiedRelationshipEvent(
                "r-context", "u1", RelationshipReason.REPAIR, RelationshipStrength.MILD,
                ConversationScope.PRIVATE, repair_at, "s2", ("s2", "s1"), "n",
            ),
        ], clock, policy)
        unlinked = project_relationship([negative, repair("r1", "s2", "missing")], clock, policy)
        premature = project_relationship([negative, repair("r1", "s2", "n", now - timedelta(hours=1))], clock, policy)
        repeated = project_relationship([negative, repair("r1", "s2", "n"), repair("r2", "s3", "n")], clock, policy)
        self.assertEqual(unlinked, baseline)
        self.assertEqual(premature, baseline)
        positive = VerifiedRelationshipEvent(
            "p", "u1", RelationshipReason.GRATITUDE, RelationshipStrength.MILD,
            ConversationScope.PRIVATE, now, "s4", ("s4",),
        )
        self.assertEqual(project_relationship([positive, repair("r1", "s2", "p")], clock, policy),
                         project_relationship([positive], clock, policy))
        self.assertGreater(baseline.tension, linked.tension)
        self.assertEqual(context.tension, linked.tension)
        self.assertEqual(repeated.tension, linked.tension)
        after_repair = project_relationship([negative, repair("r1", "s2", "n")],
                                            clock + timedelta(hours=10), policy)
        much_later = project_relationship([negative, repair("r1", "s2", "n")],
                                          clock + timedelta(days=15), policy)
        self.assertLessEqual(after_repair.tension, linked.tension)
        self.assertLess(much_later.tension, after_repair.tension)
        self.assertEqual(repeated.evidence_count, 3)
        self.assertLess(linked.trust, 0)

    def test_shared_sources_conflicting_labels_and_input_order(self) -> None:
        now = datetime(2026, 10, 26, tzinfo=timezone.utc)
        events = [
            VerifiedRelationshipEvent("g", "u1", RelationshipReason.GRATITUDE, RelationshipStrength.MILD,
                                      ConversationScope.PRIVATE, now, "s1", ("s1", "context")),
            VerifiedRelationshipEvent("duplicate", "u1", RelationshipReason.GRATITUDE, RelationshipStrength.MILD,
                                      ConversationScope.PRIVATE, now, "context", ("context",)),
            VerifiedRelationshipEvent("bad-positive", "u1", RelationshipReason.GRATITUDE, RelationshipStrength.MILD,
                                      ConversationScope.PRIVATE, now, "s3", ("s3",)),
            VerifiedRelationshipEvent("bad-negative", "u1", RelationshipReason.INSULT, RelationshipStrength.MILD,
                                      ConversationScope.PRIVATE, now, "s3", ("s3",)),
            VerifiedRelationshipEvent("respect", "u1", RelationshipReason.RESPECT, RelationshipStrength.MILD,
                                      ConversationScope.GROUP, now + timedelta(hours=1), "s4", ("s4",)),
        ]
        policy = RelationshipScoringPolicy()
        clock = now + timedelta(hours=2)
        projected = project_relationship(events, clock, policy)
        self.assertEqual(projected, project_relationship(reversed(events), clock, policy))
        self.assertEqual(projected.evidence_count, 2)
        self.assertGreater(projected.stability, 0)
        self.assertEqual(projected.last_evidence_at, (now + timedelta(hours=1)).isoformat())
        self.assertGreater(projected.trust, 0)

    def test_zero_scope_weight_and_future_events_do_not_invent_dimensions(self) -> None:
        now = datetime(2026, 10, 26, tzinfo=timezone.utc)
        event = VerifiedRelationshipEvent(
            "unknown", "u1", RelationshipReason.GRATITUDE, RelationshipStrength.MILD,
            ConversationScope.UNKNOWN, now, "s1", ("s1",),
        )
        future = VerifiedRelationshipEvent(
            "future", "u1", RelationshipReason.INSULT, RelationshipStrength.STRONG,
            ConversationScope.PRIVATE, now + timedelta(days=1), "s2", ("s2",),
        )
        projected = project_relationship([event, future], now, RelationshipScoringPolicy(unknown_weight=0))
        self.assertEqual((projected.familiarity, projected.trust, projected.warmth,
                          projected.tension, projected.stability, projected.confidence), (0, 0, 0, 0, 0, 0))
        self.assertEqual(projected.evidence_count, 0)
        missing_evidence = VerifiedRelationshipEvent(
            "no-source", "u1", RelationshipReason.INSULT, RelationshipStrength.STRONG,
            ConversationScope.PRIVATE, now, "s3", (),
        )
        self.assertEqual(project_relationship([missing_evidence], now, RelationshipScoringPolicy()),
                         RelationshipSnapshot(evaluated_at=now.isoformat()))
        with self.assertRaises(ValueError):
            project_relationship([event], now.replace(tzinfo=None), RelationshipScoringPolicy())
        with self.assertRaises(ValueError):
            project_relationship([VerifiedRelationshipEvent(
                "naive", "u1", RelationshipReason.GRATITUDE, RelationshipStrength.MILD,
                ConversationScope.PRIVATE, now.replace(tzinfo=None), "s1", ("s1",),
            )], now, RelationshipScoringPolicy())

    def test_repetition_and_scope_change_stability_and_bound_scores(self) -> None:
        now = datetime(2026, 10, 26, tzinfo=timezone.utc)
        first = VerifiedRelationshipEvent(
            "a", "u1", RelationshipReason.RESPECT, RelationshipStrength.MILD,
            ConversationScope.PRIVATE, now, "s1", ("s1",),
        )
        agreeing = VerifiedRelationshipEvent(
            "b", "u1", RelationshipReason.SUPPORT, RelationshipStrength.STRONG,
            ConversationScope.PRIVATE, now, "s2", ("s2",),
        )
        contradicting = VerifiedRelationshipEvent(
            "c", "u1", RelationshipReason.INSULT, RelationshipStrength.STRONG,
            ConversationScope.PRIVATE, now, "s3", ("s3",),
        )
        group = VerifiedRelationshipEvent(
            "b", "u1", RelationshipReason.SUPPORT, RelationshipStrength.STRONG,
            ConversationScope.GROUP, now, "s2", ("s2",),
        )
        policy = RelationshipScoringPolicy()
        one = project_relationship([first], now, policy)
        consistent = project_relationship([first, agreeing], now, policy)
        inconsistent = project_relationship([first, contradicting], now, policy)
        group_weighted = project_relationship([first, group], now, policy)
        self.assertEqual(one.stability, 0)
        self.assertGreater(consistent.stability, inconsistent.stability)
        self.assertGreater(consistent.trust, group_weighted.trust)
        self.assertGreater(consistent.familiarity, group_weighted.familiarity)
        many = [VerifiedRelationshipEvent(
            str(index), "u1", RelationshipReason.SUPPORT, RelationshipStrength.STRONG,
            ConversationScope.PRIVATE, now, str(index), (str(index),),
        ) for index in range(100)]
        bounded = project_relationship(many, now, policy)
        for value in (bounded.familiarity, bounded.tension, bounded.stability, bounded.confidence):
            self.assertGreaterEqual(value, 0)
            self.assertLessEqual(value, 1)
        for value in (bounded.trust, bounded.warmth):
            self.assertGreaterEqual(value, -1)
            self.assertLessEqual(value, 1)


if __name__ == "__main__":
    unittest.main()
