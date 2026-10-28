"""Behavior at core policy thresholds and persisted vocabulary boundaries."""

from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.domain import (
    DisclosureLevel, RecallScene, RelationshipBand, Strength,
    band_for, decide, make, recall_data, retention, validate,
)


class CorePolicyContractTest(unittest.TestCase):
    def test_disclosure_levels_include_their_exact_lower_threshold(self) -> None:
        art = make(
            "memory", {"text": "a shared fact", "level": "fact"},
            scope="shared", shareable="public",
        )
        scene = RecallScene("session", "speaker")
        # This public, same-session memory has an exposure factor of 0.9.
        for threshold, level, lower in (
            (0.55, DisclosureLevel.FULL, DisclosureLevel.PARAPHRASE),
            (0.18, DisclosureLevel.PARAPHRASE, DisclosureLevel.HINT),
            (0.03, DisclosureLevel.HINT, DisclosureLevel.SILENCE),
        ):
            with self.subTest(threshold=threshold):
                at = decide(art, scene, threshold / 0.9, ("session",))
                below = decide(art, scene, (threshold - 1e-9) / 0.9, ("session",))
                self.assertEqual(at.score, threshold)
                self.assertEqual(at.level, level)
                self.assertEqual(below.level, lower)

    def test_relationship_entry_and_exit_thresholds_preserve_hysteresis(self) -> None:
        for affinity, previous, positive, expected in (
            (-0.50, "neutral", False, "dislike"),
            (-0.50 + 1e-9, "neutral", False, "low"),
            (-0.25, "dislike", True, "dislike"),
            (-0.25 + 1e-9, "dislike", True, "low"),
            (0.90, "dislike", False, "dislike"),
            (-0.20, "neutral", False, "low"),
            (-0.20 + 1e-9, "neutral", False, "neutral"),
            (-0.10 - 1e-9, "low", False, "low"),
            (-0.10, "low", False, "neutral"),
            (0.60, "neutral", False, "close"),
            (0.60 - 1e-9, "neutral", False, "warm"),
            (0.50, "close", False, "close"),
            (0.50 - 1e-9, "close", False, "warm"),
            (0.20, "neutral", False, "warm"),
            (0.20 - 1e-9, "neutral", False, "neutral"),
            (0.10, "warm", False, "warm"),
            (0.10 - 1e-9, "warm", False, "neutral"),
        ):
            with self.subTest(affinity=affinity, previous=previous, positive=positive):
                self.assertEqual(
                    band_for(
                        affinity, 0.60, previous=RelationshipBand(previous),
                        positive_evidence=positive,
                    ).value,
                    expected,
                )
        for affinity, expected in ((-0.50, "low"), (0.60, "warm")):
            with self.subTest(affinity=affinity, confidence="below gate"):
                self.assertEqual(band_for(affinity, 0.60 - 1e-9).value, expected)

    def test_emotion_thresholds_preserve_strict_comparisons(self) -> None:
        # Neutral arousal uses the unmodified 30-day retention.
        baseline = math.exp(-1.0)
        for arousal in (0.30, 0.70):
            with self.subTest(arousal=arousal):
                self.assertAlmostEqual(
                    retention(Strength(arousal=arousal, valence=-0.30), "point", 30),
                    baseline,
                )
        high = retention(Strength(arousal=0.70 + 1e-9, valence=-0.30), "point", 30)
        low = retention(Strength(arousal=0.30 - 1e-9, valence=-0.30), "point", 30)
        self.assertGreater(high, baseline)
        self.assertLess(low, baseline)
        self.assertGreater(
            retention(Strength(arousal=0.90, valence=-0.30 - 1e-9), "point", 30),
            retention(Strength(arousal=0.90, valence=-0.30), "point", 30),
        )
        self.assertLess(
            retention(Strength(arousal=0.10, valence=-0.30 - 1e-9), "point", 30),
            retention(Strength(arousal=0.10, valence=-0.30), "point", 30),
        )

    def test_relationship_payload_keeps_existing_bands_and_version(self) -> None:
        payload = {
            "summary": "relationship state", "affinity": 0.0, "confidence": 0.0,
            "evidence_count": 0, "relation_band": "neutral",
            "policy": {
                "version": "relationship-v1", "private_weight": 1.0,
                "group_weight": 0.5, "learning_rate": 0.25, "max_revision_delta": 0.1,
            },
        }
        for band in ("close", "warm", "neutral", "low", "dislike"):
            with self.subTest(band=band):
                validate(make("relationship", {**payload, "relation_band": band}))
        for updates in (
            {"relation_band": "hostile"},
            {"policy": {**payload["policy"], "version": "relationship-v2"}},
        ):
            with self.subTest(updates=updates), self.assertRaises(ValueError):
                validate(make("relationship", {**payload, **updates}))

    def test_trace_accepts_only_existing_disclosure_values_and_bounded_counts(self) -> None:
        result = recall_data({
            "disclosure": {
                "a": "full", "b": "paraphrase", "c": "hint", "d": "silence",
                "e": "unknown", "bad id": "full",
            },
            "candidates": 1_000_000_001,
        })
        self.assertEqual(result["disclosure"], {
            "a": "full", "b": "paraphrase", "c": "hint", "d": "silence",
        })
        self.assertEqual(result["withheld_ids"], ["d"])
        self.assertEqual(result["candidates"], 1_000_000_000)


if __name__ == "__main__":
    unittest.main()
