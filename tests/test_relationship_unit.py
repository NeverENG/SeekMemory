"""Pure relationship validation and evidence scoring.

纯关系校验及证据评分。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.artifact import make, validate, content_of
from core.relationship import RelationshipSnapshot
from core.relationship_rules import (
    ConversationScope, RelationshipObservation, RelationshipReason,
    RelationshipScoringPolicy, RelationshipStrength, plan_relationship_revision,
)
from relationship_support import relationship_payload, observation

class RelationshipCoreTest(unittest.TestCase):
    def test_relationship_artifact_requires_bounded_policy_snapshot(self) -> None:
        art = make("relationship", relationship_payload(), subject_id="u1")
        validate(art)
        self.assertEqual(content_of(art), "关系状态：中性")
        broken_values = (
            ("affinity", float("nan")),
            ("confidence", 2.0),
            ("evidence_count", True),
            ("relation_band", "hostile"),
            ("policy", {}),
        )
        for key, value in broken_values:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    validate(make(
                        "relationship",
                        relationship_payload(**{key: value}),
                        subject_id="u1",
                    ))

    def test_scoring_policy_rejects_non_finite_and_unbounded_values(self) -> None:
        for kwargs in (
            {"private_weight": float("nan")},
            {"group_weight": -0.1},
            {"learning_rate": 1.1},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                RelationshipScoringPolicy(**kwargs)

    def test_private_and_group_greetings_have_exact_targets_and_deltas(self) -> None:
        current = RelationshipSnapshot(subject_id="u1")
        private = plan_relationship_revision(current, [observation(
            "private",
            RelationshipReason.FRIENDLY_GREETING,
            RelationshipStrength.MILD,
            0.95,
            ConversationScope.PRIVATE,
        )])
        group = plan_relationship_revision(current, [observation(
            "group",
            RelationshipReason.FRIENDLY_GREETING,
            RelationshipStrength.MILD,
            0.95,
            ConversationScope.GROUP,
        )])
        self.assertAlmostEqual(private.target, 0.35)
        self.assertAlmostEqual(private.delta, 0.0875)
        self.assertAlmostEqual(group.target, 0.175)
        self.assertAlmostEqual(group.delta, 0.04375)

    def test_reason_caps_review_every_fresh_artifact_but_count_one_greeting(self) -> None:
        rows = [
            observation(
                artifact_id,
                RelationshipReason.FRIENDLY_GREETING,
                RelationshipStrength.MILD,
                0.95,
                ConversationScope.PRIVATE,
            )
            for artifact_id in ("a", "b", "c")
        ]
        plan = plan_relationship_revision(
            RelationshipSnapshot(subject_id="u1"),
            rows,
            created_by_artifact_id={"a": "1", "b": "2", "c": "3"},
        )
        self.assertEqual(plan.counted_artifact_ids, ("a",))
        self.assertEqual(plan.reviewed_artifact_ids, ("a", "b", "c"))
        self.assertEqual(plan.evidence_count, 1)

    def test_mixed_reasons_use_confidence_weighted_target(self) -> None:
        gratitude = observation(
            "g",
            RelationshipReason.GRATITUDE,
            RelationshipStrength.STRONG,
            0.90,
            ConversationScope.PRIVATE,
        )
        insult = observation(
            "i",
            RelationshipReason.INSULT,
            RelationshipStrength.STRONG,
            0.60,
            ConversationScope.PRIVATE,
        )
        plan = plan_relationship_revision(
            RelationshipSnapshot(subject_id="u1"), [gratitude, insult]
        )
        expected = (0.70 * 0.90 + -0.80 * 0.60) / 1.50
        self.assertAlmostEqual(plan.target, expected)
        self.assertAlmostEqual(plan.delta, 0.25 * expected)


if __name__ == "__main__":
    unittest.main()
