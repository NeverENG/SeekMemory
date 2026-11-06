"""Authenticated loopback HTTP ingress budgets and recovery through the real listener."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import contextmanager
from http.client import HTTPResponse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class LoopbackIngressTest(unittest.TestCase):
    @contextmanager
    def _server(self):
        with tempfile.TemporaryDirectory() as tmp:
            process = subprocess.Popen(
                [sys.executable, "-B", "scripts/serve.py", "--data-dir", tmp,
                 "--port", "0", "--token", "test-only-token", "--quiet"],
                cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            try:
                endpoint = Path(tmp) / "runtime.json"
                for _ in range(100):
                    if endpoint.exists():
                        break
                    if process.poll() is not None:
                        out, err = process.communicate()
                        self.fail(f"loopback exited early: {out}\n{err}")
                    time.sleep(0.05)
                self.assertTrue(endpoint.exists())
                yield json.loads(endpoint.read_text(encoding="utf-8"))["port"]
            finally:
                self._stop(process)

    @staticmethod
    def _raw_request(port: int, raw: bytes, *, timeout: float = 8) -> tuple[int, dict]:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
            sock.sendall(raw)
            response = HTTPResponse(sock)
            response.begin()
            return response.status, json.loads(response.read() or b"{}")

    def test_oversized_body_is_rejected_before_read_and_listener_recovers(self) -> None:
        with self._server() as port:
            response = self._raw_request(port, b"POST /capture HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nAuthorization: Bearer test-only-token\r\n"
                b"Content-Length: 4194305\r\n\r\n", timeout=2)
            self.assertEqual(response, (413, {"error": "body_too_large"}))
            self.assertEqual(self._raw_request(port, b"GET /healthz HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n\r\n", timeout=2)[0], 200)

    @staticmethod
    def _post(port: int, path: str, body: object) -> tuple[int, dict]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        raw = (f"POST {path} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
               f"Authorization: Bearer test-only-token\r\n"
               f"Content-Length: {len(data)}\r\n\r\n").encode() + data
        return LoopbackIngressTest._raw_request(port, raw)

    def test_invalid_lengths_and_json_fail_without_exposing_data(self) -> None:
        with self._server() as port:
            prefix = (b"POST /capture HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                      b"Authorization: Bearer test-only-token\r\n")
            cases = (
                (b"\r\n", 411, "length_required"),
                (b"Content-Length: -1\r\n\r\n", 400, "invalid_content_length"),
                (b"Content-Length: nope\r\n\r\n", 400, "invalid_content_length"),
                (b"Content-Length: 2\r\nContent-Length: 2\r\n\r\n", 400, "invalid_content_length"),
                (b"Transfer-Encoding: chunked\r\nContent-Length: 2\r\n\r\n", 400, "invalid_content_length"),
                (b"Content-Length: 1\r\n\r\n{", 400, "invalid_json"),
                (b"Content-Length: 1\r\n\r\n\xff", 400, "invalid_json"),
            )
            for tail, status, error in cases:
                with self.subTest(tail=tail[:40]):
                    self.assertEqual(self._raw_request(port, prefix + tail),
                                     (status, {"error": error}))
            self.assertEqual(self._raw_request(port, b"GET /healthz HTTP/1.1\r\n"
                             b"Host: 127.0.0.1\r\n\r\n")[0], 200)

    def test_malformed_request_line_never_echoes_supplied_text(self) -> None:
        with self._server() as port:
            with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
                sock.sendall(b"GET /sensitive-payload extra HTTP/1.1\r\n"
                             b"Host: 127.0.0.1\r\n\r\n")
                response = HTTPResponse(sock)
                response.begin()
                self.assertEqual(response.status, 400)
                self.assertNotIn(b"sensitive-payload", response.read())
            self.assertEqual(self._raw_request(port, b"GET /healthz HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n\r\n")[0], 200)

    def test_unauthorized_oversized_request_does_not_read_body(self) -> None:
        with self._server() as port:
            self.assertEqual(self._raw_request(port, b"POST /capture HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nContent-Length: 4194305\r\n\r\n", timeout=2),
                (401, {"error": "unauthorized"}))
            self.assertEqual(self._raw_request(port, b"POST /extract/commit HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nAuthorization: Bearer test-only-token\r\n"
                b"Content-Length: 8388609\r\n\r\n", timeout=2),
                (413, {"error": "body_too_large"}))

    def test_partial_body_times_out_and_next_request_recovers(self) -> None:
        with self._server() as port:
            self.assertEqual(self._raw_request(port, b"POST /capture HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nAuthorization: Bearer test-only-token\r\n"
                b"Content-Length: 50\r\n\r\n{}"), (408, {"error": "request_timeout"}))
            self.assertEqual(self._raw_request(port, b"GET /healthz HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n\r\n")[0], 200)

    def test_partial_headers_timeout_and_next_request_recovers(self) -> None:
        with self._server() as port:
            self.assertEqual(self._raw_request(port, b"POST /capture HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nAuthorization: Bearer test-only-token\r\n"),
                (408, {"error": "request_timeout"}))
            self.assertEqual(self._raw_request(port, b"GET /healthz HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n\r\n")[0], 200)

    def test_large_authenticated_capture_and_commit_remain_usable(self) -> None:
        with self._server() as port:
            code, captured = self._post(port, "/capture", {
                "subject_key": "loopback:default", "text": "中" * 25_000,
                "role": "user", "msg_id": "large-1",
            })
            self.assertEqual(code, 200)
            self.assertTrue(captured["source_id"])
            code, plan = self._raw_request(port, b"GET /extract/plan HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nAuthorization: Bearer test-only-token\r\n\r\n")
            self.assertEqual(code, 200)
            self.assertIn(captured["source_id"], plan["source_ids"])
            code, committed = self._post(port, "/extract/commit", {
                "task_id": plan["task_id"],
                "chat_response": {"text": "[]" + " " * 200_000},
            })
            self.assertEqual(code, 200)
            self.assertGreaterEqual(committed["skipped"], 1)

    def test_premature_eof_rejects_partial_body_and_listener_recovers(self) -> None:
        with self._server() as port:
            with socket.create_connection(("127.0.0.1", port), timeout=3) as sock:
                sock.sendall(b"POST /capture HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    b"Authorization: Bearer test-only-token\r\nContent-Length: 9\r\n\r\n{}")
                sock.shutdown(socket.SHUT_WR)
                response = HTTPResponse(sock)
                response.begin()
                self.assertEqual((response.status, json.loads(response.read())),
                                 (400, {"error": "incomplete_body"}))
            self.assertEqual(self._raw_request(port, b"GET /healthz HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n\r\n")[0], 200)

    def test_trickled_headers_cannot_extend_total_deadline(self) -> None:
        with self._server() as port:
            with socket.create_connection(("127.0.0.1", port), timeout=4) as sock:
                sock.sendall(b"POST /capture HTTP/1.1\r\nHost: 127.0.0.1\r\nX-Test: ")
                stop = threading.Event()

                def trickle() -> None:
                    while not stop.wait(0.3):
                        try:
                            sock.sendall(b"x")
                        except OSError:
                            break

                sender = threading.Thread(target=trickle, daemon=True)
                sender.start()
                try:
                    response = HTTPResponse(sock)
                    response.begin()
                    self.assertEqual((response.status, json.loads(response.read())),
                                     (408, {"error": "request_timeout"}))
                finally:
                    stop.set()
                    sender.join(timeout=1)
            self.assertEqual(self._raw_request(port, b"GET /healthz HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n\r\n")[0], 200)

    def test_trickled_body_cannot_extend_total_deadline(self) -> None:
        with self._server() as port:
            with socket.create_connection(("127.0.0.1", port), timeout=8) as sock:
                sock.sendall(b"POST /capture HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                    b"Authorization: Bearer test-only-token\r\nContent-Length: 100\r\n\r\n{")
                stop = threading.Event()

                def trickle() -> None:
                    while not stop.wait(0.3):
                        try:
                            sock.sendall(b" ")
                        except OSError:
                            break

                sender = threading.Thread(target=trickle, daemon=True)
                sender.start()
                try:
                    response = HTTPResponse(sock)
                    response.begin()
                    self.assertEqual((response.status, json.loads(response.read())),
                                     (408, {"error": "request_timeout"}))
                finally:
                    stop.set()
                    sender.join(timeout=1)
            self.assertEqual(self._raw_request(port, b"GET /healthz HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\n\r\n")[0], 200)

    def test_large_authored_persona_keeps_existing_write_path(self) -> None:
        with self._server() as port:
            code, saved = self._post(port, "/persona", {
                "subject_key": "loopback:default", "text": "中" * 1900,
            })
            self.assertEqual(code, 200)
            self.assertEqual(saved["chars"], 1900)
            code, fetched = self._raw_request(port, b"GET /persona HTTP/1.1\r\n"
                b"Host: 127.0.0.1\r\nAuthorization: Bearer test-only-token\r\n\r\n")
            self.assertEqual(code, 200)
            self.assertEqual(fetched["text"], "中" * 1900)

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
