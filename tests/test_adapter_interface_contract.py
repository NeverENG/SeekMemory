"""Protect SDK-free shared adapter exports and existing protocol identities.

保护不依赖 SDK 的共享适配器导出及既有协议身份。
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class AdapterInterfaceContractTest(unittest.TestCase):
    def test_shared_entries_keep_explicit_original_objects(self):
        from adapters import domain

        expected = {
            "FilePersonaPacks": "persona_packs", "RelationshipReader": "relationship_policy",
            "RelationshipInteractionPolicy": "relationship_policy", "settings_from_config": "relationship_policy",
            "interaction_prompt": "relationship_policy",
        }
        self.assertEqual(set(domain.__all__), set(expected))
        for name, owner in expected.items():
            self.assertIs(getattr(domain, name), getattr(importlib.import_module("adapters." + owner), name))

    def test_shared_protocols_keep_identity(self):
        from app import ports as app_ports
        from adapters import ports

        for name in ports.__all__:
            self.assertIs(getattr(ports, name), getattr(app_ports, name))


if __name__ == "__main__":
    unittest.main()
