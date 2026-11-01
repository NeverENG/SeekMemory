"""Authenticated persona writes preserve revisions across a kernel restart."""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import closing
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

from adapters.loopback.runtime import MemoryService
from services.management_service import ManagementService
from store import open_store
from store.cache import Cache

ROOT = Path(__file__).resolve().parents[1]


class PersonaWriteLoopbackTest(unittest.TestCase):
    def test_write_guards_audit_and_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            data = base / "copy"
            config = {"owner_umo": "test:owner"}
            seeded = MemoryService(source, config, quiet=True)
            try:
                seeded.management_service.bootstrap_persona({
                    "id": "test-self", "version": "1.0.0", "name": "Test Self",
                    "persona": "first version", "style": {"tone": "warm"},
                    "boundaries": ["be accurate"],
                    "corpus": [{"user": f"u{i} " + "u" * 50,
                                "assistant": f"a{i} " + "a" * 50}
                               for i in range(12)],
                })
            finally:
                seeded.store.close()
            data.mkdir()
            with closing(sqlite3.connect(source / "memory.db")) as original:
                with closing(sqlite3.connect(data / "memory.db")) as copy:
                    original.backup(copy)
            config_file = data / "kernel-config.json"
            config_file.write_text(json.dumps(config), encoding="utf-8")

            process = self.start_kernel(data, config_file)
            try:
                before = self.request(data, "/persona?subject_key=test:owner")
                self.assertEqual(before, (200, {"text": "first version", "chars": 13,
                                                "revision": 1}))
                self.assertEqual(self.request(data, "/persona", method="POST",
                                              body={"subject_key": "other", "text": "x"})[0], 403)
                self.assertEqual(self.request(data, "/persona", method="POST",
                                              body={"subject_key": "test:owner", "text": "  "})[0], 400)
                self.assertEqual(self.request(data, "/persona", method="POST",
                                              body={"subject_key": "test:owner", "text": "x" * 2001})[0], 400)
                self.assertEqual(self.request(data, "/persona", method="POST",
                                              body={"subject_key": "test:owner", "text": "x"},
                                              authorized=False)[0], 401)
                written = self.request(data, "/persona", method="POST", body={
                    "subject_key": "test:owner", "text": "  second version  ",
                    "note": "self edit\nchecked",
                })
                self.assertEqual(written, (200, {"revision": 2, "chars": 14}))
                after = self.request(data, "/persona?subject_key=test:owner")
                self.assertEqual(after, (200, {"text": "second version", "chars": 14,
                                               "revision": 2}))
                audit_lines = (data / "persona-writes.log").read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(audit_lines), 1)
                audit = json.loads(audit_lines[0])
                self.assertEqual((audit["revision"], audit["chars"], audit["note"]),
                                 (2, 14, "self edit\nchecked"))
                self.assertNotIn("second version", audit_lines[0])
                print("write: revision 1 -> 2; empty=400 long=400 foreign=403 unauthorized=401; audit=1")
            finally:
                self.stop_kernel(process)

            (data / "runtime.json").unlink()
            process = self.start_kernel(data, config_file)
            try:
                persisted = self.request(data, "/persona?subject_key=test:owner")
                self.assertEqual(persisted[1]["revision"], 2)
                self.assertEqual(persisted[1]["text"], "second version")
            finally:
                self.stop_kernel(process)
            store = open_store(str(data / "memory.db"))
            try:
                active = store.artifacts.list(family="persona", state="active")
                self.assertEqual(len(active), 1)
                self.assertEqual(len(store.artifacts.history(active[0].header.id)), 2)
                self.assertEqual(active[0].payload["style"], {"tone": "warm"})
                self.assertEqual(active[0].payload["corpus_count"], 12)
                self.assertEqual(len(active[0].payload["corpus"]), 12)
                self.assertEqual(active[0].header.lineage.sources, ())
                print("restart: revision 2 persisted; versions=2; style/corpus preserved; lineage empty")
                cache = Cache(store.artifacts)
                cache.load()
                management = ManagementService(store.artifacts, store.sources,
                                               store.ledger, cache, None)
                restored = management.rollback_persona({
                    "id": active[0].header.id, "revision": 1,
                    "reason": "test rollback", "confirmed": True,
                })
                self.assertEqual(restored["revision"], 3)
                self.assertEqual(store.artifacts.get(active[0].header.id).payload["text"],
                                 "first version")
                print("rollback: restored revision 1 as new revision 3")
            finally:
                store.close()

    @staticmethod
    def start_kernel(data: Path, config_file: Path) -> subprocess.Popen[str]:
        process = subprocess.Popen(
            [sys.executable, "-B", "scripts/serve.py", "--data-dir", str(data),
             "--port", "0", "--token", "test-only-token", "--config", str(config_file),
             "--quiet"], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )
        runtime_file = data / "runtime.json"
        for _ in range(100):
            if runtime_file.exists():
                return process
            if process.poll() is not None:
                stdout, stderr = process.communicate()
                raise AssertionError(f"kernel exited early: {stdout} {stderr}")
            time.sleep(0.05)
        process.terminate()
        process.communicate(timeout=5)
        raise AssertionError("kernel startup timeout")

    @staticmethod
    def stop_kernel(process: subprocess.Popen[str]) -> None:
        if process.poll() is None:
            process.terminate()
        process.communicate(timeout=5)

    @staticmethod
    def request(data: Path, path: str, *, method: str = "GET", body: dict | None = None,
                authorized: bool = True) -> tuple[int, dict]:
        runtime = json.loads((data / "runtime.json").read_text(encoding="utf-8"))
        headers = {"authorization": "Bearer test-only-token"} if authorized else {}
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        if payload is not None:
            headers["content-type"] = "application/json"
        req = Request(f"http://127.0.0.1:{runtime['port']}{path}", data=payload,
                      method=method, headers=headers)
        try:
            response = build_opener(ProxyHandler({})).open(req, timeout=4)
        except HTTPError as exc:
            response = exc
        with response:
            return response.status, json.loads(response.read())


if __name__ == "__main__":
    unittest.main()
