"""Behavior at core policy thresholds and persisted vocabulary boundaries."""

from __future__ import annotations

import math
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.domain import (
    DisclosureLevel, RecallScene, Strength,
    decide, make, recall_data, retention,
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
