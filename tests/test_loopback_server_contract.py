"""Loopback entry preserves the CLI and reports the incomplete extraction contract honestly."""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener
from unittest.mock import Mock, patch

from adapters.loopback import server
from adapters.loopback.runtime import MemoryService

ROOT = Path(__file__).resolve().parents[1]


class LoopbackServerContractTest(unittest.TestCase):
    def test_transport_and_composition_belong_to_adapter(self) -> None:
        self.assertEqual(server.make_handler.__module__, "adapters.loopback.server")
        self.assertEqual(MemoryService.__module__, "adapters.loopback.runtime")

    def test_cli_endpoints_and_failure_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "data"
            process = subprocess.Popen(
                [sys.executable, "-B", "scripts/serve.py", "--data-dir", str(data_dir),
                 "--port", "0", "--token", "test-only-token", "--quiet"],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            self.addCleanup(self._stop, process)
            runtime_file = data_dir / "runtime.json"
            for _ in range(100):
                if runtime_file.exists():
                    break
                if process.poll() is not None:
                    stdout, stderr = process.communicate()
                    self.fail(f"loopback exited early: {stdout}\n{stderr}")
                time.sleep(0.05)
            self.assertTrue(runtime_file.exists(), "loopback did not publish runtime metadata")
            runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
            self.assertEqual(runtime["token"], "test-only-token")
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(runtime_file.stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE(data_dir.stat().st_mode), 0o700)
            base = f"http://127.0.0.1:{runtime['port']}"
            opener = build_opener(ProxyHandler({}))

            def request(path: str, *, method: str = "GET", body: object = None,
                        authorized: bool = True) -> tuple[int, dict | None]:
                headers = {"authorization": "Bearer test-only-token"} if authorized else {}
                data = None
                if body is not None:
                    headers["content-type"] = "application/json"
                    data = json.dumps(body).encode()
                req = Request(base + path, data=data, method=method, headers=headers)
                try:
                    response = opener.open(req, timeout=3)
                except HTTPError as exc:
                    response = exc
                with response:
                    raw = response.read()
                    return response.status, json.loads(raw) if raw else None

            code, health = request("/healthz", authorized=False)
            self.assertEqual(code, 200)
            self.assertNotIn("db", health)
            self.assertEqual(request("/status", authorized=False)[0], 401)
            self.assertEqual(request("/extract/plan")[0], 204)
            code, captured = request("/capture", method="POST", body={
                "subject_key": "test:local:owner", "role": "user", "text": "hello",
                "msg_id": "m1", "at": "2026-10-31T00:00:00+08:00",
            })
            self.assertEqual(code, 200)
            self.assertTrue(captured["source_id"])
            code, plan = request("/extract/plan")
            self.assertEqual(code, 200)
            self.assertIn("hello", plan["chat_request"]["prompt"])
            self.assertEqual(request("/extract/commit", method="POST", body={
                "task_id": "unknown", "source_ids": plan["source_ids"],
                "chat_response": {"text": "[]"},
            })[0], 409)
            self.assertEqual(request("/extract/commit", method="POST", body={
                "task_id": plan["task_id"], "source_ids": ["forged"],
                "chat_response": {"text": "[]"},
            })[0], 409)
            code, committed = request("/extract/commit", method="POST", body={
                "task_id": plan["task_id"], "chat_response": {"text": "[]"},
            })
            self.assertEqual(code, 200)
            self.assertEqual(committed["skipped"], 1)
            self.assertEqual(request("/extract/plan")[0], 204)
            code, failure = request("/capture", method="POST", body=["sensitive"],
                                    authorized=True)
            self.assertEqual((code, failure), (500, {"error": "internal_error"}))

    def test_listener_creation_failure_closes_store(self) -> None:
        fake = Mock()
        with patch.object(server, "MemoryService", return_value=fake), patch.object(
            server, "HTTPServer", side_effect=OSError("bind failed")
        ):
            with self.assertRaises(OSError):
                server.serve(Path("/unused"))
        fake.store.close.assert_called_once()

    @staticmethod
    def _stop(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.terminate()
        try:
            process.communicate(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()


if __name__ == "__main__":
    unittest.main()
