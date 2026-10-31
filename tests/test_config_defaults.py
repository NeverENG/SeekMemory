"""Keep host-facing defaults aligned with the SeekMemory configuration owner."""

import json
import unittest
from pathlib import Path

from app.config import (AttentionSettings, DEFAULTS, FIELDS, GROUPS,
                        ProactiveSettings, RuntimeSettings, Settings)


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

    def test_attention_and_proactive_defaults_are_host_independent(self):
        settings = Settings()
        attention = AttentionSettings.read(settings.get)
        proactive = ProactiveSettings.read(settings.get)
        self.assertTrue(attention.policy_enabled)
        self.assertEqual(attention.followup_rounds, 3)
        self.assertFalse(proactive.enabled)
        self.assertEqual(proactive.idle_seconds, 1800.0)
        changed = Settings({"attention_followup_rounds": 2,
                            "proactive_enabled": True,
                            "proactive_idle_seconds": 60})
        self.assertEqual(AttentionSettings.read(changed.get).followup_rounds, 2)
        self.assertTrue(ProactiveSettings.read(changed.get).enabled)
        self.assertEqual(ProactiveSettings.read(changed.get).idle_seconds, 60.0)

    def test_runtime_settings_can_be_reread_without_freezing_host_overrides(self):
        overrides: dict[str, object] = {}
        settings = Settings(overrides)
        original = RuntimeSettings.read(settings.get)
        self.assertEqual(original.effective_wait_seconds, 0)
        self.assertFalse(original.gate_enabled)
        self.assertEqual(original.tick_seconds, 5.0)
        overrides.update(runtime_gate_enabled=True, runtime_wait_seconds=12,
                         runtime_tick_seconds=2, runtime_dispatch_max_attempts=4)
        updated = RuntimeSettings.read(settings.get)
        self.assertEqual(updated.effective_wait_seconds, 12)
        self.assertEqual(updated.tick_seconds, 2.0)
        self.assertEqual(updated.dispatch_max_attempts, 4)
        self.assertEqual(original.effective_wait_seconds, 0)

    def test_each_key_has_seekmemory_metadata(self):
        self.assertEqual(set(FIELDS), set(DEFAULTS))
        self.assertEqual({key: spec.default for key, spec in FIELDS.items()}, dict(DEFAULTS))
        self.assertEqual(FIELDS["owner_umo"].level, "basic")
        self.assertEqual(FIELDS["recall_min_ev_abs"].level, "internal")
        self.assertEqual(FIELDS["runtime_gate_enabled"].stability, "experimental")
        self.assertEqual(FIELDS["ingest_enabled"].group, "ingest")
        self.assertEqual(FIELDS["attention_policy_enabled"].group, "attention")
        self.assertEqual(FIELDS["proactive_enabled"].group, "proactive")
        self.assertEqual(FIELDS["dream_enabled"].group, "dream")

    def test_host_schema_projects_shared_defaults(self):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        hidden = {"ingest_enabled", "ingest_interval_seconds", "ingest_min_pending", "ingest_batch_topics"}
        self.assertEqual(set(schema), set(DEFAULTS) - hidden)
        self.assertEqual({k: v["default"] for k, v in schema.items()},
                         {k: DEFAULTS[k] for k in schema})
        keys = [key for group in GROUPS.values() for key in group]
        self.assertEqual(len(keys), len(set(keys)))
        self.assertEqual(set(keys), set(DEFAULTS))


class ConfigReadAuditTest(unittest.TestCase):
    def test_literal_policy_reads_are_registered_and_have_consistent_fallbacks(self):
        """Audit static keys without claiming to cover computed policy keys."""
        import ast

        root = SCHEMA.parent
        reads: dict[str, list[tuple[str, object]]] = {}
        for directory in ("adapters", "services", "app", "recall", "maintain", "perceive"):
            for path in (root / directory).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if not isinstance(node, ast.Call) or not node.args:
                        continue
                    fn = node.func
                    if isinstance(fn, ast.Attribute):
                        policy_read = fn.attr in ("_c", "config")
                    else:
                        policy_read = isinstance(fn, ast.Name) and fn.id == "conf"
                    if not policy_read or not isinstance(node.args[0], ast.Constant):
                        continue
                    key = node.args[0].value
                    if not isinstance(key, str):
                        continue
                    try:
                        fallback = ast.literal_eval(node.args[1])
                    except (IndexError, ValueError, TypeError):
                        fallback = None
                    reads.setdefault(key, []).append((str(path.relative_to(root)), fallback))
        self.assertTrue(reads)
        self.assertEqual(set(reads) - set(DEFAULTS), set())
        mismatches = {
            key: values for key, values in reads.items()
            if any(value is not None and value != DEFAULTS[key] for _, value in values)
        }
        self.assertEqual(mismatches, {})


if __name__ == "__main__":
    unittest.main()
