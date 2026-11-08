"""Loopback E2E against the real memory service and its AgentRuntime ingress."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RuntimeServiceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.data_dir = tempfile.TemporaryDirectory(prefix="seekmem-runtime-")
        self.process = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "serve.py"),
             "--data-dir", self.data_dir.name, "--token", "test-token", "--quiet"],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.endpoint = self._wait_endpoint()

    def tearDown(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.data_dir.cleanup()

    def _wait_endpoint(self):
        path = Path(self.data_dir.name) / "runtime.json"
        for _ in range(100):
            try:
                return json.loads(path.read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                time.sleep(0.02)
        self.fail("memory service did not publish runtime.json")

    def _post(self, path: str, body: dict):
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.endpoint['port']}{path}",
            data=json.dumps(body).encode(),
            headers={
                "authorization": "Bearer test-token",
                "content-type": "application/json",
            },
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            return response.status, json.loads(response.read())

    def test_accept_user_and_context_are_served_by_real_runtime(self) -> None:
        status, receipt = self._post("/runtime/events", {
            "kind": "accept_user",
            "event_id": "event-1",
            "input": {
                "session_id": "dsh-session-a",
                "text": "下周见？",
                "event_time": 10.0,
                "received_at": 12.5,
                "speaker_id": "local:single:owner",
                "private": False,
                "mentioned": True,
                "question": True,
                "scene": "group",
                "role": "member",
                "addressed": True,
                "event_id": "event-1",
                "kind": "message",
            },
        })
        self.assertEqual(status, 200)
        self.assertEqual(receipt["decision"]["action"], "reply")
        self.assertEqual(receipt["decision"]["reason"], "direct_attention")
        self.assertTrue(receipt["source_id"])
        self.assertEqual(receipt["turn_id"], "event-1")
        plan = urllib.request.Request(
            f"http://127.0.0.1:{self.endpoint['port']}/extract/plan?subject_key=loopback:default",
            headers={"authorization": "Bearer test-token"},
        )
        with urllib.request.urlopen(plan, timeout=2) as response:
            self.assertIn(receipt["source_id"], json.load(response)["source_ids"])

        status, context = self._post("/runtime/context", {
            "session_id": "dsh-session-a",
            "query": "下周见？",
            "speaker_id": "owner",
            "event_time": 10.0,
            "received_at": 12.5,
            "now": 13.0,
            "reason": "inbound",
        })
        self.assertEqual(status, 200)
        self.assertIn("text", context)
        self.assertIsInstance(context["info"], dict)

    def test_unknown_dsh_input_field_keeps_existing_bad_request(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._post("/runtime/events", {
                "kind": "accept_user", "input": {
                    "session_id": "s", "text": "hello", "host_object": {},
                },
            })
        self.assertEqual(caught.exception.code, 400)
        plan = urllib.request.Request(
            f"http://127.0.0.1:{self.endpoint['port']}/extract/plan?subject_key=loopback:default",
            headers={"authorization": "Bearer test-token"},
        )
        with urllib.request.urlopen(plan, timeout=2) as response:
            self.assertEqual(response.status, 204, "invalid host facts must not create a Source")

    def test_loopback_requires_bearer_token(self) -> None:
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.endpoint['port']}/runtime/events",
            data=b"{}",
            headers={"content-type": "application/json"},
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=2)
        self.assertEqual(caught.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
