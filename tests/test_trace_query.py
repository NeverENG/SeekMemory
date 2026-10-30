"""Host-neutral trace query behavior over real producers and bounded storage."""

from __future__ import annotations

import importlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType, SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
package = ModuleType("_seekmemory_trace_query")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package
TraceStore = importlib.import_module(f"{package.__name__}.store.run_trace").TraceStore
RunTracer = importlib.import_module(f"{package.__name__}.app.runtime.tracing").RunTracer
query_traces = importlib.import_module(f"{package.__name__}.services.trace_query").query_traces


def event():
    extras = {}
    return SimpleNamespace(get_extra=extras.get, set_extra=extras.__setitem__)


class TraceQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "runs.jsonl"
        self.now = 1_800_000_000.0
        self.store = TraceStore(self.path, clock=lambda: self.now)
        tracer = RunTracer(self.store, clock=lambda: self.now)
        failed, completed, running = event(), event(), event()
        tracer.begin(failed)
        tracer.request(failed, {"mode": "strict", "query": "PRIVATE_SENTINEL",
                               "final_ids": ["n_1"]})
        self.now += 10
        tracer.response(failed, "error")
        tracer.done(failed, "error")
        self.failed = tracer.run_id(failed)
        self.end = datetime.fromtimestamp(self.now, timezone.utc)
        self.now += 10
        tracer.begin(completed)
        tracer.request(completed, {})
        tracer.done(completed, "ok")
        tracer.delivered(completed)
        self.completed = tracer.run_id(completed)
        tracer.begin(running)
        self.running = tracer.run_id(running)

    def test_combined_inclusive_filters_keep_the_complete_available_timeline(self):
        # Bounds describe the same instant in different timezone notations.
        query = {"run_id": self.failed, "status": "error",
                 "state": "recalled_and_injected", "since": self.end.isoformat(),
                 "until": self.end.astimezone(timezone(timedelta(hours=8))).isoformat()}
        result = query_traces(self.store.snapshot, query)
        self.assertEqual([r["id"] for r in result["runs"]], [self.failed])
        self.assertEqual([e["sequence"] for e in result["events"]], [1, 2, 3, 4])
        self.assertLess(result["events"][0]["at"], query["since"])
        for values in ({"since": (self.end + timedelta(seconds=1)).isoformat()},
                       {"until": (self.end - timedelta(seconds=1)).isoformat()},
                       {"status": "completed"}, {"state": "not_recalled"}):
            self.assertEqual(query_traces(self.store.snapshot, {"run_id": self.failed, **values})["runs"], [])
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))

    def test_status_filters_and_legacy_default_preserve_snapshot_metadata(self):
        self.assertEqual(query_traces(self.store.snapshot, {}), self.store.snapshot())
        for status, run_id in (("running", self.running), ("completed", self.completed),
                               ("error", self.failed)):
            result = query_traces(self.store.snapshot, {"status": status})
            self.assertEqual([r["id"] for r in result["runs"]], [run_id])
            self.assertEqual({e["run_id"] for e in result["events"]}, {run_id})
            self.assertEqual(result["capacity"], 5000)
            self.assertEqual(result["retention_days"], 7)
        self.assertEqual(query_traces(self.store.snapshot, {"run_id": "0" * 32})["runs"], [])
        self.now += 1
        restored = TraceStore(self.path, clock=lambda: self.now, read_only=True)
        result = query_traces(restored.snapshot, {"status": "interrupted"})
        self.assertEqual([r["id"] for r in result["runs"]], [self.running])

    def test_reload_revalidates_private_fields_and_query_never_rewrites_file(self):
        row = self.store.snapshot()["events"][0]
        with self.path.open("a") as stream:
            stream.write("{broken\n")
            stream.write(json.dumps({**row, "message": "PRIVATE_SENTINEL",
                                     "subject_id": "PRIVATE_SENTINEL"}) + "\n")
        original = self.path.read_bytes()
        restored = TraceStore(self.path, clock=lambda: self.now, read_only=True)
        result = query_traces(restored.snapshot, {"run_id": self.failed})
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(result))
        self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_queries_reject_without_echoing_private_input(self):
        for query in ({"status": "PRIVATE_SENTINEL"}, {"state": "PRIVATE_SENTINEL"},
                      {"run_id": "PRIVATE_SENTINEL"}, {"since": "PRIVATE_SENTINEL"},
                      {"until": "PRIVATE_SENTINEL"}, {"since": "2026-10-29T12:00:00"},
                      {"since": "2026-10-29T12:00:01Z", "until": "2026-10-29T12:00:00Z"}):
            with self.subTest(query=query), self.assertRaises(ValueError) as raised:
                query_traces(self.store.snapshot, query)
            self.assertNotIn("PRIVATE_SENTINEL", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
