"""Protect explicit maintenance entries and required protocol identities.

保护明确的维护入口及所需协议身份。
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EXPORTS = {
    "decay_all": "decay", "forget_expired": "lifecycle", "merge_similar": "merge",
    "revise_impression": "impression", "build_self_impressions": "self_impression",
    "promote_self_candidates": "self_impression", "compose": "persona",
    "distill_persona": "persona", "distill_self_persona": "persona",
    "consolidate_relationships": "relationship", "link_new": "link", "persist": "link",
    "signals": "reflect", "should_reflect": "reflect", "promote_candidates": "promote",
    "RevisionWrite": "plans", "RevisionPlan": "plans",
}


class MaintainInterfaceContractTest(unittest.TestCase):
    def test_supported_exports_keep_original_objects(self):
        domain = importlib.import_module("maintain.domain")
        self.assertEqual(set(domain.__all__), set(EXPORTS))
        for name, owner in EXPORTS.items():
            self.assertIs(getattr(domain, name), getattr(importlib.import_module("maintain." + owner), name))

    def test_required_protocols_are_reused(self):
        from app import ports as app_ports
        from maintain import ports

        for name in ports.__all__:
            self.assertIs(getattr(ports, name), getattr(app_ports, name))


if __name__ == "__main__":
    unittest.main()
