"""Protect supported persistence entries and shared-connection ownership.

保护受支持的持久化入口及共享连接归属。
"""
from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

EXPORTS = {
    "Store": "composition", "open_store": "composition", "ArtifactRepository": "artifacts",
    "SourceRepository": "sources", "ExtractionRepository": "extraction", "Ledger": "ledger",
    "LedgerRepository": "ledger", "chain_hash": "ledger", "chain_payload": "ledger",
    "RuntimeStateRepository": "runtime_state", "RuntimeEpisodeRepository": "runtime_episodes",
    "DreamRepository": "dreams", "StoreMetricsRepository": "metrics", "Cache": "cache",
    "TraceStore": "run_trace",
}


class StoreInterfaceContractTest(unittest.TestCase):
    def test_explicit_exports_keep_original_objects(self):
        domain = importlib.import_module("store.domain")
        package = importlib.import_module("store")
        self.assertEqual(set(domain.__all__), set(EXPORTS))
        for name, owner in EXPORTS.items():
            self.assertIs(getattr(domain, name), getattr(importlib.import_module("store." + owner), name))
        self.assertIs(package.Store, domain.Store)
        self.assertIs(package.open_store, domain.open_store)

    def test_repository_bundle_borrows_one_connection(self):
        from store.domain import open_store

        store = open_store(":memory:")
        self.addCleanup(store.close)
        for name in ("artifacts", "sources", "extraction", "ledger", "runtime_state",
                     "runtime_episodes", "dreams", "metrics"):
            self.assertIs(getattr(store, name).conn, store.conn)

    def test_old_codec_helper_imports_remain_compatible(self):
        from store import artifact_codec, artifact_sql, serialization, sqlite

        for name in ("dump_json", "load_json_any", "load_json_object", "pick_dataclass_fields"):
            self.assertIs(getattr(sqlite, name), getattr(serialization, name))
        self.assertEqual(artifact_codec.SELECT_SQL, artifact_sql.SELECT_SQL)
        self.assertEqual(artifact_codec.UPSERT_SQL, artifact_sql.UPSERT_SQL)
        self.assertEqual(sqlite.dump_json({"z": "中文", "a": [1]}), '{"a": [1], "z": "中文"}')


if __name__ == "__main__":
    unittest.main()
