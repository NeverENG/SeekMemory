"""Real loopback HTTP, authentication and revision tests without a chat host."""

from __future__ import annotations

import http.client
import importlib
import json
import os
import select
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from threading import Barrier
from types import ModuleType, SimpleNamespace
from urllib.parse import quote, urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))
from contract_support import ROOT, validate_contract
from persona_pack_fixture import pack

package = ModuleType("_seekmemory_http_tests")
package.__path__ = [str(ROOT)]
sys.modules[package.__name__] = package


def module(name: str):
    return importlib.import_module(f"{package.__name__}.{name}")


class ConsoleHttpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        with_store = module("store").open_store(str(self.data / "memory.db"))
        self.art = module("core.artifact").make(
            "memory", {"text": "Original fact", "level": "fact"}, id="memory/encoded id",
        )
        with_store.artifacts.commit(self.art, expected_revision=0, op="create")
        with_store.close()
        self.token = "test-console-admin-token-1234567890"
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts/console_http.py"),
             "--data-dir", str(self.data), "--port", "0",
             "--allow-origin", "http://127.0.0.1:5176"],
            cwd=ROOT, env={**os.environ, "SEEKMEMORY_CONSOLE_TOKEN": self.token},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.addCleanup(self.stop)
        self.assertTrue(select.select([self.process.stdout], [], [], 10)[0], "startup timeout")
        line = self.process.stdout.readline().strip()
        self.assertTrue(line.startswith("SeekMemory console: http://127.0.0.1:"), line)
        self.port = int(line.rsplit(":", 1)[1])

    def stop(self) -> None:
        self.process.terminate()
        stdout, stderr = self.process.communicate(timeout=10)
        self.assertNotIn(self.token, stdout + stderr)
        self.assertNotIn("Original fact", stdout + stderr)

    def request(self, path: str, method: str = "GET", body: object = None,
                *, auth: bool = True, headers: dict | None = None,
                raw: bytes | None = None, timeout: float = 5):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=timeout)
        try:
            fields = {"Authorization": f"Bearer {self.token}"} if auth else {}
            fields.update(headers or {})
            if raw is None and body is not None:
                raw = json.dumps(body).encode()
                fields["Content-Type"] = "application/json"
            connection.request(method, path, raw, fields)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            connection.close()

    def api(self, action: str, method: str = "GET", body: object = None,
            expected: int = 200):
        status, _, raw = self.request(f"/api/manage/{action}", method, body)
        data = json.loads(raw)
        self.assertEqual(status, expected, data)
        validate_contract(action.split("?")[0], data, status)
        return data

    def test_auth_origin_methods_and_bounded_bodies(self) -> None:
        for path in ("records", "detail?id=x", "traces", "packArtwork"):
            status, headers, raw = self.request(f"/api/manage/{path}", auth=False)
            self.assertEqual(status, 401)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertNotIn(b"Original fact", raw)
        for headers in ({"Origin": "https://evil.example"}, {"Host": "evil.example"}):
            self.assertEqual(self.request("/api/manage/records", headers=headers)[0], 403)
        self.api("records", "POST", {}, expected=405)
        self.api("update", "GET", expected=405)
        self.api("records", "PUT", expected=405)
        self.api("update", "POST", [], expected=400)
        self.assertEqual(self.request("/api/manage/update", "POST", raw=b"{")[0], 400)
        self.assertEqual(self.request("/api/manage/update", "POST", raw=b"x" * 65537)[0], 413)
        self.assertEqual(self.request("/api/manage/nope")[0], 404)
        status, headers, _ = self.request("/api/manage/records", "OPTIONS", auth=False,
                                        headers={"Origin": "http://127.0.0.1:5176"})
        self.assertEqual(status, 204)
        self.assertEqual(headers["Access-Control-Allow-Origin"], "http://127.0.0.1:5176")
        self.assertNotIn("Access-Control-Allow-Credentials", headers)

    def test_reads_use_real_data_and_preserve_contracts(self) -> None:
        records = self.api("records")["records"]
        self.assertEqual([row["text"] for row in records], ["Original fact"])
        detail = self.api(f"detail?id={quote(self.art.header.id)}")
        self.assertEqual(detail["artifact"]["header"]["id"], self.art.header.id)
        status = self.api("status")
        self.assertEqual(status["capabilities"], {"maintenanceTasks": False})
        for action in ("graph", "impressions", "dream", "events", "traces", "packs"):
            self.api(action)
        self.api("detail?id=absent", expected=404)
        self.api("packs?offset=invalid", expected=400)
        self.api("task", "POST", {"kind": "extract", "confirmed": True}, expected=503)

    def test_update_keeps_revision_history_and_rejects_stale_writes(self) -> None:
        command = {
            "id": self.art.header.id, "expectedRevision": 1,
            "payload": {"text": "Updated fact", "level": "fact"},
            "scope": "private", "state": "active", "reason": "Correction", "confirmed": True,
        }
        self.api("update", "POST", {**command, "confirmed": False}, expected=400)
        self.api("update", "POST", command)
        self.api("update", "POST", command, expected=409)
        detail = self.api(f"detail?id={quote(self.art.header.id)}")
        self.assertEqual(detail["artifact"]["header"]["revision"], 2)
        self.assertEqual({json.loads(row["content"])["text"] for row in detail["versions"]},
                         {"Original fact", "Updated fact"})
        self.assertEqual(len(detail["ledger"]), 2)

    def test_idle_connections_do_not_block_authenticated_requests(self) -> None:
        with ExitStack() as connections:
            for _ in range(2):
                connections.enter_context(socket.create_connection(("127.0.0.1", self.port)))
            status, _, raw = self.request("/api/manage/status", timeout=2)
            self.assertEqual(status, 200, raw)
            validate_contract("status", json.loads(raw))
            self.api("update", "POST", {
                "id": self.art.header.id, "expectedRevision": 1,
                "payload": {"text": "Updated while idle", "level": "fact"},
                "scope": "private", "state": "active", "reason": "Correction", "confirmed": True,
            })

    def test_concurrent_updates_keep_one_revision_and_ledger_entry(self) -> None:
        barrier = Barrier(2)

        def update(text: str) -> int:
            barrier.wait(timeout=5)
            status, _, _ = self.request("/api/manage/update", "POST", {
                "id": self.art.header.id, "expectedRevision": 1,
                "payload": {"text": text, "level": "fact"},
                "scope": "private", "state": "active", "reason": "Correction", "confirmed": True,
            })
            return status

        with ThreadPoolExecutor(max_workers=2) as clients:
            self.assertEqual(sorted(clients.map(update, ("First edit", "Second edit"))), [200, 409])
        detail = self.api(f"detail?id={quote(self.art.header.id)}")
        self.assertEqual(detail["artifact"]["header"]["revision"], 2)
        self.assertEqual(len(detail["versions"]), 2)
        self.assertEqual(len(detail["ledger"]), 2)
        self.assertTrue(all(check["ok"] for check in self.api("status")["checks"]))

    def test_interrupt_closes_runtime_on_its_owner_thread(self) -> None:
        self.api("status")
        self.process.send_signal(signal.SIGINT)
        _, stderr = self.process.communicate(timeout=10)
        self.assertEqual(self.process.returncode, 0, stderr)

    def test_persona_preview_conflict_artwork_and_diagnostics(self) -> None:
        preview = self.api("pack?reference=official/big_fish")
        self.api("packExport?reference=official/big_fish")
        self.api("packArtwork?reference=official/big_fish", expected=404)
        imported = self.api("persona", "POST", {
            "operation": "importPack", "pack": pack(preview["seed"]), "confirmed": True,
        })
        self.api(f"packArtwork?reference={imported['reference']}")
        command = {"operation": "install", "reference": "official/big_fish",
                   "expectedId": None, "expectedRevision": 0,
                   "expectedDigest": preview["digest"], "confirmed": True}
        self.api("persona", "POST", {**command, "expectedDigest": "stale"}, expected=409)
        installed = self.api("persona", "POST", command)
        self.assertEqual(self.api("status")["persona"]["id"], installed["id"])
        self.api("persona", "POST", command, expected=409)
        self.api("diagnose", "POST", {"query": "coffee", "umo": "bot:FriendMessage:test",
                                      "speaker": "test"})
        self.api("pack?reference=mine/../secret", expected=400)

    def test_trace_privacy_and_static_path_boundaries(self) -> None:
        # Reload in a new process to exercise persisted trace revalidation.
        self.process.terminate()
        self.process.communicate(timeout=10)
        from datetime import datetime, timedelta, timezone
        trace_path = self.data / "run_traces.jsonl"
        row = {
            "run_id": "a" * 32, "sequence": 1, "event": "agent_begin",
            "at": datetime.now(timezone.utc).isoformat(), "status": "running",
            "message": "PRIVATE_SENTINEL", "subject_id": "PRIVATE_SENTINEL",
        }
        old_row = {**row, "run_id": "b" * 32,
                   "at": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()}
        trace_path.write_text(json.dumps(old_row) + "\n" + json.dumps(row) + "\n{broken\n")
        writer = module("store.run_trace").TraceStore(trace_path)
        tracer = module("app.runtime.tracing").RunTracer(writer)
        extras = {}
        event = SimpleNamespace(get_extra=extras.get, set_extra=extras.__setitem__)
        tracer.begin(event)
        tracer.request(event, {"query": "PRIVATE_SENTINEL", "mode": "strict",
                               "final_ids": ["n_1"]})
        tracer.response(event, "error")
        tracer.done(event, "error")
        # Reintroduce old/private/corrupt rows after the producer has finished.
        with trace_path.open("a") as stream:
            stream.write(json.dumps(old_row) + "\n" + json.dumps(row) + "\n{broken\n")
        original = trace_path.read_bytes()
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts/console_http.py"), "--data-dir",
             str(self.data), "--port", "0"], cwd=ROOT,
            env={**os.environ, "SEEKMEMORY_CONSOLE_TOKEN": self.token},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.assertTrue(select.select([self.process.stdout], [], [], 10)[0])
        self.port = int(self.process.stdout.readline().strip().rsplit(":", 1)[1])
        self.assertEqual(trace_path.read_bytes(), original)
        trace = self.api("traces")
        self.assertNotIn("b" * 32, [run["id"] for run in trace["runs"]])
        self.api("traces?state=not_recalled")
        self.assertEqual(trace_path.read_bytes(), original)
        query = urlencode({"run_id": tracer.run_id(event), "status": "error",
                           "since": writer.snapshot()["runs"][0]["updated_at"]})
        matched = self.api(f"traces?{query}")
        self.assertEqual([r["id"] for r in matched["runs"]], [tracer.run_id(event)])
        self.assertEqual([e["event"] for e in matched["events"]],
                         ["agent_begin", "llm_request", "llm_response", "agent_done"])
        self.assertTrue(all(e["status"] == "error" for e in matched["events"][-2:]))
        self.assertEqual(trace_path.read_bytes(), original)
        for field in ("run_id", "state", "status", "since", "until"):
            rejected = self.api(f"traces?{field}=PRIVATE_SENTINEL", expected=400)
            self.assertNotIn("PRIVATE_SENTINEL", json.dumps(rejected))
        self.assertNotIn("PRIVATE_SENTINEL", json.dumps(trace))
        for path in ("/../openapi.yaml", "/assets/%2e%2e/%2e%2e/openapi.yaml", "/main.py"):
            self.assertEqual(self.request(path, auth=False)[0], 404)


class ConsoleStartupTests(unittest.TestCase):
    def test_invalid_auth_and_origins_fail_before_opening_data(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "not-created"
            for token, extra in (
                ("", []), ("short", []), ("x" * 32 + "\n", []),
                ("x" * 32, ["--allow-origin", "https://example.com"]),
                ("x" * 32, ["--port", "-1"]),
            ):
                with self.subTest(extra=extra, token_length=len(token)):
                    process = subprocess.run(
                        [sys.executable, str(ROOT / "scripts/console_http.py"),
                         "--data-dir", str(data), *extra],
                        cwd=ROOT, env={**os.environ, "SEEKMEMORY_CONSOLE_TOKEN": token},
                        capture_output=True, text=True, timeout=10,
                    )
                    self.assertEqual(process.returncode, 2)
                    self.assertFalse(data.exists())


if __name__ == "__main__":
    unittest.main()
