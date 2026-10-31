"""Keep host-facing defaults aligned with the SeekMemory configuration owner."""

import json
import unittest
from pathlib import Path

from app.config import DEFAULTS, GROUPS, Settings


SCHEMA = Path(__file__).resolve().parents[1] / "_conf_schema.json"


class ConfigDefaultsTest(unittest.TestCase):
    def test_empty_configuration_uses_seekmemory_defaults(self):
        settings = Settings()
        self.assertEqual(settings.get("open_to", ""), "owner_only")
        self.assertFalse(settings.get("runtime_gate_enabled", True))
        self.assertTrue(settings.get("ingest_enabled", False))
        self.assertEqual(settings.get("ingest_interval_seconds", 1), 600)
        self.assertEqual(settings.get("unknown", 7), 7)

    def test_old_overrides_and_fallback_coercion(self):
        settings = Settings({"recall_k": "12", "dream_enabled": None, "open_to": "everyone"})
        self.assertEqual(settings.get("recall_k", 8), 12)
        self.assertTrue(settings.get("dream_enabled", True))
        self.assertEqual(settings.get("open_to", "owner_only"), "everyone")
        self.assertEqual(Settings({"recall_k": "bad"}).get("recall_k", 8), 8)

    def test_host_schema_projects_shared_defaults(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        hidden = {"ingest_enabled", "ingest_interval_seconds", "ingest_min_pending", "ingest_batch_topics"}
        self.assertEqual(set(schema), set(DEFAULTS) - hidden)
        self.assertEqual({k: v["default"] for k, v in schema.items()},
                         {k: DEFAULTS[k] for k in schema})
        keys = [key for group in GROUPS.values() for key in group]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), set(DEFAULTS))


if __name__ == "__main__":
    unittest.main()
