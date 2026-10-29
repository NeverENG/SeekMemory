"""Check offline script cleanup and preserved output after failed publication.

验证离线脚本清理及发布失败后原产物保留。
"""

from __future__ import annotations

from contextlib import closing, redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import bootstrap_persona, runtime_http, snapshot_db
from store import open_store


class ScriptResourcesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def test_failed_snapshot_preserves_previous_file_and_same_path_is_rejected(self):
        source, output = self.root / "source.db", self.root / "backup.db"
        with closing(sqlite3.connect(source)) as conn, conn:
            conn.execute("CREATE TABLE evidence (value TEXT)")
            conn.execute("INSERT INTO evidence VALUES ('kept')")
        snapshot_db.snapshot(str(source), str(output))
        previous = output.read_bytes()
        with patch.object(snapshot_db.os, "replace", side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                snapshot_db.snapshot(str(source), str(output))
        self.assertEqual(output.read_bytes(), previous)
        self.assertEqual(list(self.root.glob(".*.tmp")), [])
        with self.assertRaises(ValueError):
            snapshot_db.snapshot(str(source), str(source))
        with closing(sqlite3.connect(output)) as conn:
            self.assertEqual(conn.execute("SELECT value FROM evidence").fetchone()[0], "kept")

    def test_destination_open_failure_closes_snapshot_source_connection(self):
        source, output = self.root / "source.db", self.root / "backup.db"
        sqlite3.connect(source).close()
        connect = sqlite3.connect
        opened = []

        def fail_second(*args, **kwargs):
            if opened:
                raise OSError("destination unavailable")
            conn = connect(*args, **kwargs)
            opened.append(conn)
            return conn

        with patch.object(snapshot_db.sqlite3, "connect", side_effect=fail_second):
            with self.assertRaises(OSError):
                snapshot_db.snapshot(str(source), str(output))
        with self.assertRaises(sqlite3.ProgrammingError):
            opened[0].execute("SELECT 1")
        self.assertFalse(output.exists())

    def test_persona_script_closes_store_after_success_and_failure(self):
        seed = self.root / "persona.json"
        seed.write_text(json.dumps({"id": "fixture"}), encoding="utf-8")
        for failed in (False, True):
            db = open_store(":memory:")
            with patch.object(bootstrap_persona, "Store", return_value=db), patch.object(
                bootstrap_persona.ManagementService, "bootstrap_persona",
                side_effect=ValueError("invalid") if failed else None, return_value={"id": "fixture"},
            ), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                status = bootstrap_persona.main(["--db", "unused", "--file", str(seed)])
            self.assertEqual(status, int(failed))
            with self.assertRaises(sqlite3.ProgrammingError):
                db.conn.execute("SELECT 1")

    def test_endpoint_metadata_failure_closes_the_http_listener(self):
        servers = []
        server_type = runtime_http.ThreadingHTTPServer

        def create(*args, **kwargs):
            server = server_type(*args, **kwargs)
            servers.append(server)
            return server

        with patch.object(sys, "argv", ["runtime_http", "--data-dir", str(self.root)]), patch.object(
            runtime_http, "ThreadingHTTPServer", side_effect=create,
        ), patch.object(runtime_http.Path, "write_text", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                runtime_http.main()
        self.assertEqual(servers[0].socket.fileno(), -1)


if __name__ == "__main__":
    unittest.main()
