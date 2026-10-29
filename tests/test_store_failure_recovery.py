"""Verify cache publication, connection cleanup and observable failed writes.

验证缓存发布、连接清理及可识别的写入失败。
"""
from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.artifact import make, revise
from store import open_store
from store.cache import Cache
from store.run_trace import TraceStore
from store.sqlite import SqliteDatabase


class StoreRecoveryTest(unittest.TestCase):
    def setUp(self):
        self.db = open_store(":memory:")
        self.addCleanup(self.db.close)
        self.cache = Cache(self.db.artifacts)
        self.art = make("memory", {"level": "fact", "text": "已有记忆"}, subject_id="u")
        self.db.artifacts.commit(self.art, expected_revision=0, op="create")
        self.cache.load()

    def assert_cache_unchanged(self, version):
        self.assertEqual(self.cache.version, version)
        self.assertEqual(self.cache.active(), [self.art])
        self.assertEqual(self.cache.by_level("fact"), [self.art])
        self.assertEqual(self.cache.by_subject("u"), [self.art])
        self.assertEqual(self.cache.active("memory"), [self.art])

    def test_failed_cache_read_keeps_old_indices_and_version(self):
        version = self.cache.version
        with patch.object(self.db.artifacts, "list", side_effect=OSError("read failed")):
            with self.assertRaises(OSError):
                self.cache.load()
        self.assert_cache_unchanged(version)
        self.cache.load()
        self.assertGreater(self.cache.version, version)

    def test_failed_cache_rebuild_keeps_whole_previous_snapshot(self):
        version = self.cache.version
        valid = make("memory", {"text": "另一条记忆", "level": "detail"})
        broken = replace(revise(self.art), payload=None)
        with patch.object(self.db.artifacts, "list", return_value=[valid, broken]):
            with self.assertRaises(AttributeError):
                self.cache.load()
        self.assert_cache_unchanged(version)

    def test_failed_replacement_preparation_keeps_existing_memory(self):
        version = self.cache.version
        broken = replace(revise(self.art), payload=None)
        with self.assertRaises(AttributeError):
            self.cache.put(broken)
        self.assert_cache_unchanged(version)

    def test_single_and_group_commit_reject_unknown_operations_before_writes(self):
        latest = revise(self.art, payload={"text": "新版本", "level": "fact"})
        with self.assertRaises(ValueError):
            self.db.artifacts.commit(latest, expected_revision=1, op="unknown")
        with self.assertRaises(ValueError):
            self.db.artifacts.commit_many([(latest, 1, ())], op="unknown")
        self.assertEqual(self.db.artifacts.get(self.art.header.id), self.art)
        self.assertEqual(len(self.db.ledger.entries()), 1)

    def test_failed_migration_closes_new_connection(self):
        connections = []
        original = sqlite3.connect

        def connect(*args, **kwargs):
            result = original(*args, **kwargs)
            connections.append(result)
            return result

        with patch("store.sqlite.sqlite3.connect", side_effect=connect), \
             patch("store.sqlite.migrate", side_effect=OSError("migration failed")):
            with self.assertRaises(OSError):
                SqliteDatabase(":memory:")
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute("SELECT 1")

    def test_failed_repository_composition_closes_new_connection(self):
        databases = []

        def database(path):
            result = SqliteDatabase(path)
            databases.append(result)
            return result

        with patch("store.composition.SqliteDatabase", side_effect=database), \
             patch("store.composition.ArtifactRepository", side_effect=RuntimeError("construction failed")):
            with self.assertRaises(RuntimeError):
                open_store(":memory:")
        with self.assertRaises(sqlite3.ProgrammingError):
            databases[0].conn.execute("SELECT 1")


class TraceRecoveryTest(unittest.TestCase):
    def test_failed_trace_write_raises_and_retains_saved_snapshot(self):
        from app.runtime.tracing import RunTracer

        class Event:
            def __init__(self):
                self.extra = {}

            def get_extra(self, key, default=None):
                return self.extra.get(key, default)

            def set_extra(self, key, value):
                self.extra[key] = value

        with tempfile.TemporaryDirectory() as temporary:
            store = TraceStore(Path(temporary) / "trace.jsonl", max_rows=1)
            tracer = RunTracer(store)
            event = Event()
            tracer.begin(event)
            rows = store.snapshot()["events"]
            before = store.path.read_bytes()
            newer = {**rows[0], "sequence": 2}
            with patch("store.run_trace.os.replace", side_effect=OSError("write failed")):
                with self.assertRaises(OSError):
                    store.append(newer)
                self.assertTrue(store.persistence_error)
                self.assertEqual(store.snapshot()["events"], rows)
                self.assertEqual(store.path.read_bytes(), before)
                tracer.request(event, {})  # Diagnostics stay isolated from the host / 诊断失败仍与宿主隔离。
            tracer.done(event, "ok")
            self.assertFalse(store.persistence_error)
            self.assertEqual(store.snapshot()["events"][0]["event"], "agent_done")


if __name__ == "__main__":
    unittest.main()
