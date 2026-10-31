"""Manifest schema tests: frozen cards must fail loudly when edited incorrectly."""

from __future__ import annotations

import copy
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchmarks.long_horizon.manifest import (  # noqa: E402
    ManifestError,
    fingerprint,
    load_manifest,
    parse_manifest,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MANIFEST = os.path.join(ROOT, "benchmarks", "data", "long_horizon_manifest.json")


def _raw() -> dict:
    with open(MANIFEST, encoding="utf-8") as handle:
        return json.load(handle)


class ManifestTest(unittest.TestCase):
    def test_committed_manifest_is_valid_and_complete(self) -> None:
        manifest = load_manifest(MANIFEST)
        self.assertEqual(manifest.horizons, (7, 30, 60, 90))
        self.assertGreaterEqual(len(manifest.scenarios), 4)
        for scenario in manifest.scenarios:
            self.assertEqual([checkpoint.day for checkpoint in scenario.checkpoints], [7, 30, 60, 90])
            self.assertTrue(scenario.events, scenario.id)
            for checkpoint in scenario.checkpoints:
                self.assertTrue(checkpoint.expect_tokens)
                self.assertTrue(checkpoint.emotion)
                self.assertTrue(checkpoint.relationship_bands)

    def test_every_privacy_scenario_declares_a_marker(self) -> None:
        manifest = load_manifest(MANIFEST)
        privacy = [scenario for scenario in manifest.scenarios if "privacy" in scenario.tokens]
        self.assertTrue(privacy, "at least one scenario must declare a privacy marker")

    def test_fingerprint_is_stable_and_content_addressed(self) -> None:
        first = fingerprint(load_manifest(MANIFEST))
        second = fingerprint(load_manifest(MANIFEST))
        self.assertEqual(first["digest"], second["digest"])
        data = _raw()
        data["scenarios"][0]["title"] += " (changed)"
        changed = fingerprint(parse_manifest(data))
        self.assertNotEqual(first["digest"], changed["digest"])

    def test_milestones_are_ordered_and_typed(self) -> None:
        manifest = load_manifest(MANIFEST)
        kinds = {event.kind for scenario in manifest.scenarios for event in scenario.milestones}
        self.assertIn("restart", kinds)
        self.assertIn("rollback", kinds)
        for scenario in manifest.scenarios:
            days = [event.day for event in scenario.milestones]
            self.assertEqual(days, sorted(days), scenario.id)

    def test_unknown_schema_is_rejected(self) -> None:
        data = _raw()
        data["schema"] = "seekmemory.long_horizon.manifest.v0"
        with self.assertRaises(ManifestError):
            parse_manifest(data)

    def test_missing_checkpoint_is_rejected(self) -> None:
        data = _raw()
        del data["scenarios"][0]["checkpoints"]["60"]
        with self.assertRaises(ManifestError):
            parse_manifest(data)

    def test_undeclared_token_in_checkpoint_is_rejected(self) -> None:
        data = _raw()
        data["scenarios"][0]["checkpoints"]["7"]["expect_tokens"] = ["not-a-declared-token"]
        with self.assertRaises(ManifestError):
            parse_manifest(data)

    def test_expected_and_forbidden_token_cannot_overlap(self) -> None:
        data = _raw()
        checkpoint = data["scenarios"][0]["checkpoints"]["7"]
        checkpoint["forbid_tokens"] = list(checkpoint["expect_tokens"])
        with self.assertRaises(ManifestError):
            parse_manifest(data)

    def test_unsigned_rollback_milestone_is_rejected(self) -> None:
        data = copy.deepcopy(_raw())
        scenario = next(item for item in data["scenarios"] if item["id"] == "fact_correction")
        rollback = next(item for item in scenario["milestones"] if item["kind"] == "rollback")
        del rollback["revision"]
        with self.assertRaises(ManifestError):
            parse_manifest(data)

    def test_out_of_order_events_are_rejected(self) -> None:
        data = _raw()
        events = data["scenarios"][0]["events"]
        events[0], events[1] = events[1], events[0]
        with self.assertRaises(ManifestError):
            parse_manifest(data)

    def test_interval_bounds_must_be_ordered(self) -> None:
        data = _raw()
        data["scenarios"][0]["checkpoints"]["7"]["emotion"]["affection"] = [90, 45]
        with self.assertRaises(ManifestError):
            parse_manifest(data)


if __name__ == "__main__":
    unittest.main()
