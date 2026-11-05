"""Adapt authenticated loopback HTTP to memory services; own listener lifetime.

适配本机 HTTP 协议并负责监听器生命周期，不实现记忆算法。
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

from .bounded_io import DeadlineReader, IngressError
from .runtime import HOST_CONTRACT, MemoryService


# Byte ceilings apply to the encoded JSON on the wire, not decoded characters.
POST_BYTES = 4 * 1024 * 1024
COMMIT_BYTES = 8 * 1024 * 1024
HEADER_SECONDS = 2
BODY_SECONDS = 5


def make_handler(service: MemoryService, token: str):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def setup(self) -> None:
            super().setup()
            self.rfile = DeadlineReader(self.connection, self.rfile, HEADER_SECONDS)

        def handle(self) -> None:
            try:
                super().handle()
            except IngressError as exc:
                # No complete request line: a response cannot be framed reliably.
                self.close_connection = True
                if self.request_version != "HTTP/0.9":
                    try:
                        self._send(exc.status, {"error": exc.reason})
                    except OSError:
                        pass
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def send_error(self, code: int, message: str | None = None,
                       explain: str | None = None) -> None:
            # The standard handler echoes malformed request lines in its HTML error.
            self.close_connection = True
            try:
                self._send(code, {"error": "bad_request"})
            except OSError:
                pass

        def log_message(self, fmt: str, *args: Any) -> None:  # 静音默认日志
            return

        def _send(self, code: int, payload: dict | None) -> None:
            if code == 204 or payload is None:
                self.send_response(204)
                self.send_header("content-length", "0")
                self.end_headers()
                return
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _auth_ok(self) -> bool:
            header = self.headers.get("authorization") or ""
            return hmac.compare_digest(header, f"Bearer {token}")

        def _route(self, method: str) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/healthz":
                code, payload = service.healthz()
                return self._send(code, payload)
            if not self._auth_ok():
                return self._send(401, {"error": "unauthorized"})
            query = {}
            if "?" in self.path:
                from urllib.parse import parse_qs
                query = {k: v[-1] for k, v in parse_qs(self.path.split("?", 1)[1]).items()}
            try:
                if path == "/runtime/events" and method == "POST":
                    return self._send(*service.runtime_event(self._read_body()))
                if path == "/runtime/context" and method == "POST":
                    return self._send(*service.runtime_context(self._read_body()))
                if path == "/capture" and method == "POST":
                    return self._send(*service.capture(self._read_body()))
                if path == "/recall" and method == "POST":
                    return self._send(*service.recall(self._read_body()))
                if path == "/persona" and method == "GET":
                    return self._send(*service.persona(query))
                if path == "/persona" and method == "POST":
                    return self._send(*service.persona_write(self._read_body()))
                if path == "/status" and method == "GET":
                    return self._send(*service.status())
                if path == "/extract/plan" and method == "GET":
                    return self._send(*service.extract_plan(query))
                if path == "/extract/commit" and method == "POST":
                    return self._send(*service.extract_commit(self._read_body()))
            except IngressError as exc:
                self.close_connection = True  # Unread body bytes must not become another request.
                return self._send(exc.status, {"error": exc.reason})
            except Exception:  # 不泄漏异常文本、正文或本机路径。
                return self._send(500, {"error": "internal_error"})
            return self._send(404, {"error": "not found"})

        def _read_body(self) -> dict:
            lengths = self.headers.get_all("content-length", [])
            if self.headers.get("transfer-encoding") or len(lengths) > 1:
                raise IngressError(400, "invalid_content_length")
            if not lengths:
                raise IngressError(411, "length_required")
            value = lengths[0].strip()
            if not value or any(char < "0" or char > "9" for char in value):
                raise IngressError(400, "invalid_content_length")
            limit = COMMIT_BYTES if self.path.split("?", 1)[0] == "/extract/commit" else POST_BYTES
            significant = value.lstrip("0") or "0"
            if len(significant) > len(str(limit)) or int(significant) > limit:
                raise IngressError(413, "body_too_large")
            length = int(significant)
            if length == 0:
                return {}
            raw = self.rfile.read_exact(length, seconds=BODY_SECONDS)
            try:
                return json.loads(raw.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise IngressError(400, "invalid_json") from exc

        def do_GET(self) -> None:  # noqa: N802
            self._route("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._route("POST")

    return Handler



def _publish_runtime(path: Path, metadata: dict[str, Any]) -> None:
    """Atomically replace connection metadata with owner-only token permissions."""
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=".runtime-",
                                         encoding="utf-8", delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(metadata, handle, ensure_ascii=False)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def serve(data_dir: Path, *, port: int = 0, token: str = "",
          config: dict[str, Any] | None = None, quiet: bool = False) -> None:
    """Bind loopback, publish compatible discovery metadata and close owned resources."""
    service = MemoryService(data_dir, config, quiet=quiet)
    try:
        credential = token or secrets.token_urlsafe(24)
        server = HTTPServer(("127.0.0.1", port), make_handler(service, credential))
        try:
            runtime = {"port": server.server_address[1], "token": credential,
                       "host_contract": HOST_CONTRACT}
            _publish_runtime(data_dir / "runtime.json", runtime)
            print(f"memory kernel listening on 127.0.0.1:{server.server_address[1]}", flush=True)
            print(f"runtime file: {data_dir / 'runtime.json'}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
        finally:
            server.server_close()
    finally:
        service.store.close()
