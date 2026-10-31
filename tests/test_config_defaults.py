"""Keep host-facing defaults aligned with the SeekMemory configuration owner."""

import json
import unittest
from pathlib import Path

from app.config import (ALIASES, CONFIG_VERSION, CONFLICTS, DEPENDENCIES,
                        PROFILES, AttentionSettings,
                        DEFAULTS, FIELDS, GROUPS, POLICIES, inspect_overrides,
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
        self.assertEqual(set(POLICIES), set(GROUPS))
        self.assertIn("runtime_gate_enabled", POLICIES["runtime"].advanced_overrides)
        self.assertEqual(CONFLICTS, ())
        self.assertEqual({d.trigger for d in DEPENDENCIES},
                         {"proactive_enabled", "relationship_mode"})
        self.assertEqual(FIELDS["weekly_day"].maximum, 6)
        self.assertEqual(FIELDS["relationship_mode"].choices, ("off", "observe", "enforce"))
        self.assertTrue(FIELDS["db_path"].restart_required)
        self.assertTrue(FIELDS["runtime_gate_enabled"].restart_required)
        self.assertFalse(FIELDS["runtime_tick_seconds"].restart_required)

    def test_manifest_profiles_are_explicit_and_do_not_enable_unsafe_gates(self):
        self.assertEqual(CONFIG_VERSION, 1)
        self.assertEqual(dict(ALIASES), {})
        self.assertEqual(set(PROFILES), {"quiet", "balanced", "engaged", "developer"})
        self.assertEqual(dict(PROFILES["balanced"].overrides), {})
        for profile in PROFILES.values():
            self.assertEqual(inspect_overrides(profile.overrides), ())
            self.assertFalse(profile.overrides.get("runtime_gate_enabled", False))
            self.assertFalse(profile.overrides.get("proactive_enabled", False))
            self.assertNotEqual(profile.overrides.get("relationship_mode"), "enforce")
        self.assertEqual(Settings({"config_profile": "engaged"}).get("recall_k", 8), 8)

    def test_advisory_validation_and_dependencies_never_rewrite_input(self):
        overrides = {"relationship_mode": "enforce", "proactive_enabled": True,
                     "runtime_wait_seconds": -1, "recall_k": "many",
                     "weekly_day": 8, "unrecognized": 1}
        before = dict(overrides)
        warnings = inspect_overrides(overrides)
        self.assertEqual(overrides, before)
        self.assertEqual({(w.code, w.key) for w in warnings}, {
            ("requires_runtime_gate", "relationship_mode"),
            ("requires_runtime_gate", "proactive_enabled"),
            ("inactive_override", "runtime_wait_seconds"),
            ("out_of_range", "runtime_wait_seconds"),
            ("invalid_type", "recall_k"), ("out_of_range", "weekly_day"),
            ("unknown_key", "unrecognized"),
        })
        self.assertEqual(inspect_overrides({}), ())
        self.assertEqual(inspect_overrides({"config_version": 1}), ())
        self.assertEqual(inspect_overrides({"config_version": 2})[0].code,
                         "unsupported_version")
        self.assertEqual(inspect_overrides({"config_profile": []})[0].code,
                         "unknown_profile")
        self.assertEqual(inspect_overrides({"config_profile": "quiet"})[0].code,
                         "profile_not_applied")
        self.assertEqual(inspect_overrides({"runtime_gate_enabled": True,
                                            "relationship_mode": "enforce"}), ())

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
    def test_production_config_has_no_astrbot_or_yaml_import(self):
        """Documentation and OpenAPI tooling may use YAML; policy loading may not."""
        import ast

        config_dir = SCHEMA.parent / "app" / "config"
        for path in config_dir.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imports = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    imports = [node.module or ""] if node.level == 0 else []
                else:
                    continue
                self.assertFalse(
                    any(name.split(".")[0] in {"astrbot", "yaml"} for name in imports),
                    str(path),
                )

    def test_helper_forwarded_keys_are_in_contract(self):
        """Cover literals passed to known wrappers around computed key reads."""
        import ast

        root = SCHEMA.parent
        wrappers = {
            "app/budget.py": {"_num", "_bool"},
            "recall/pipeline.py": {"_conf_bool"},
            "adapters/relationship_policy.py": {"probability"},
            "services/maintenance_service.py": {"_relationship_weight"},
        }
        observed: set[str] = set()
        for name, methods in wrappers.items():
            tree = ast.parse((root / name).read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                method = node.func.attr if isinstance(node.func, ast.Attribute) else (
                    node.func.id if isinstance(node.func, ast.Name) else "")
                if method in methods and isinstance(node.args[0], ast.Constant):
                    key = node.args[0].value
                    if isinstance(key, str):
                        observed.add(key)
        self.assertEqual(observed, {
            "budget_chars", "context_system_chars", "group_context_messages",
            "history_messages", "source_recall_enabled", "source_recall_hours",
            "source_recall_max_candidates", "relationship_private_weight",
            "relationship_group_weight", "relationship_low_private_reply_probability",
            "relationship_dislike_private_reply_probability",
        })
        self.assertTrue(observed <= set(FIELDS))

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
