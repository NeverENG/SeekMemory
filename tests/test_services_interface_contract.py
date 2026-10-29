"""Protect the supported service surface and both import modes.

保护已支持的服务接口及两种导入方式。
"""
from __future__ import annotations

import importlib
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Explicit compatibility contract, independent of future implementation names.
# 明确的兼容契约，不由今后的实现命名自动扩张。
EXPORTS = {
    "AccessPolicy": "access_service", "AccessService": "access_service",
    "BackgroundService": "background_service", "CapacityService": "capacity_service",
    "IngestService": "ingest_service", "MaintenanceService": "maintenance_service",
    "ManagementService": "management_service", "RecallService": "recall_service",
    "ServiceCollection": "service_collection", "StatusService": "status_service",
    "TreeService": "tree_service",
}


class ServicesInterfaceContractTest(unittest.TestCase):
    def test_supported_exports_keep_identity(self) -> None:
        domain = importlib.import_module("services.domain")
        package = importlib.import_module("services")
        self.assertEqual(set(domain.__all__), set(EXPORTS))
        for name, owner in EXPORTS.items():
            original = getattr(importlib.import_module("services." + owner), name)
            self.assertIs(getattr(domain, name), original)
            self.assertIs(getattr(package, name), original)

    def test_reused_ports_keep_identity(self) -> None:
        from app import ports as app_ports
        from services import ports

        for name in ("ArtifactStore", "ArtifactCache", "SourceStore", "ExtractionStore",
                     "ChatModel", "TreeArtifactStore", "TreeCache"):
            self.assertIs(getattr(ports, name), getattr(app_ports, name))

    def test_fresh_import_orders_work_in_both_modes(self) -> None:
        script = """
import importlib, sys, types
root = sys.argv[1]
package = types.ModuleType('seekmemory_contract')
package.__path__ = [root]
sys.modules[package.__name__] = package
for name in sys.argv[2:]:
    importlib.import_module(name)
"""
        for order in (
            ("services.ports", "services.domain", "app.ports", "store"),
            ("app.ports", "store", "services.domain", "services.ports"),
            ("seekmemory_contract.services.ports", "seekmemory_contract.services.domain",
             "seekmemory_contract.app.ports", "seekmemory_contract.store"),
            ("seekmemory_contract.app.ports", "seekmemory_contract.store",
             "seekmemory_contract.services.domain"),
        ):
            with self.subTest(order=order):
                result = subprocess.run(
                    [sys.executable, "-X", "utf8", "-B", "-c", script, str(ROOT), *order],
                    cwd=ROOT, capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
