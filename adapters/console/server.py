"""Loopback HTTP boundary for the independent management console."""

from __future__ import annotations

import argparse
import hmac
import json
import mimetypes
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from ...webui.console_api import ApiResponse, error
from .worker import ConsoleWorker

ROOT = Path(__file__).resolve().parents[2]


def local_origin(value: str) -> str:
    """Allow explicit loopback browser origins only, without credentials or paths."""
    parsed = urlsplit(value)
    if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.username or parsed.password or parsed.path not in {"", "/"}
            or parsed.query or parsed.fragment or parsed.port is None):
        raise ValueError("origin 必须为带端口的本机 HTTP 地址")
    return f"http://{parsed.netloc}"


class ConsoleServer(ThreadingHTTPServer):
    """Read connections concurrently, then serialize management work separately."""

    daemon_threads = False  # Drain handlers before closing the runtime worker.

    def __init__(self, port: int, api: ConsoleWorker, token: str, *,
                 static_dir: Path = ROOT / "pages/memory",
                 allowed_origins: tuple[str, ...] = ()) -> None:
        if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
            raise ValueError("管理员令牌必须为至少 32 个无空白 ASCII 字符")
        origins = {local_origin(value) for value in allowed_origins}
        self.api = api
        self.token = token
        self.static_dir = static_dir.resolve()
        super().__init__(("127.0.0.1", port), ConsoleHandler)
        self.hosts = {f"127.0.0.1:{self.server_port}", f"localhost:{self.server_port}"}
        self.origins = origins | {f"http://{host}" for host in self.hosts}


class ConsoleHandler(BaseHTTPRequestHandler):
    server: ConsoleServer

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(10)

    def log_message(self, *_args: object) -> None:
        """Never log URLs, request bodies, credentials or identifiers."""

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; "
                         "script-src 'self'; style-src 'self' 'unsafe-inline'; "
                         "img-src 'self' data:; font-src 'self' data:; "
                         "connect-src 'self' http://127.0.0.1:* http://localhost:*; "
                         "frame-ancestors 'none'; base-uri 'none'")
        origin = self.headers.get("Origin")
        if origin in self.server.origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, response: ApiResponse) -> None:
        self._send(response.status, json.dumps(response.data, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def _boundary(self) -> bool:
        if (self.headers.get("Host") not in self.server.hosts
                or self.headers.get("Origin", "") not in self.server.origins | {""}):
            self._json(error(403, "请求来源不允许"))
            return False
        return True

    def do_OPTIONS(self) -> None:
        if self._boundary():
            self._send(204, b"", "text/plain")

    def do_GET(self) -> None:
        self._handle()

    def do_POST(self) -> None:
        self._handle()

    def do_PUT(self) -> None:
        self._handle()

    def do_DELETE(self) -> None:
        self._handle()

    def _handle(self) -> None:
        if not self._boundary():
            return
        parsed = urlsplit(self.path)
        if not parsed.path.startswith("/api/"):
            self._static(parsed.path)
            return
        supplied = self.headers.get("Authorization", "").encode()
        expected = f"Bearer {self.server.token}".encode()
        if not hmac.compare_digest(supplied, expected):
            self._json(error(401, "需要管理员令牌"))
            return
        prefix = "/api/manage/"
        if not parsed.path.startswith(prefix):
            self._json(error(404, "未知操作"))
            return
        action = parsed.path[len(prefix):]
        body = None
        if self.command == "POST":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.headers.get("Transfer-Encoding") or length < 0:
                    raise ValueError("invalid_length")
                if length > (3 * 1024 * 1024 if action == "persona" else 65536):
                    self._json(error(413, "请求内容过大"))
                    return
                body = json.loads(self.rfile.read(length))
            except (ValueError, UnicodeError):
                self._json(error(400, "请求体必须为有效 JSON"))
                return
        query = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        self._json(self.server.api.handle(action, self.command, query, body))

    def _static(self, path: str) -> None:
        if self.command != "GET":
            self._json(error(405, "请求方法不支持"))
            return
        relative = unquote(path).lstrip("/") or "index.html"
        target = (self.server.static_dir / relative).resolve()
        allowed = (relative in {"index.html", "LICENSES.md", "ASSET-LICENSES.txt"}
                   or relative.startswith("assets/"))
        if not allowed or not target.is_relative_to(self.server.static_dir) or not target.is_file():
            self._json(error(404, "页面不存在，请先构建 dashboard"))
            return
        self._send(200, target.read_bytes(), mimetypes.guess_type(target.name)[0]
                   or "application/octet-stream")


def main(argv: list[str] | None = None) -> int:
    """Start a local console using explicitly selected data and administrator token."""
    parser = argparse.ArgumentParser(description="SeekMemory standalone console")
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--allow-origin", action="append", default=[],
                        help="允许访问 API 的本机开发页面 origin，可重复")
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error("port 必须为 0–65535")
    token = os.environ.get("SEEKMEMORY_CONSOLE_TOKEN", "")
    if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        parser.error("设置 SEEKMEMORY_CONSOLE_TOKEN：至少 32 个无空白 ASCII 字符")
    try:
        origins = tuple(local_origin(value) for value in args.allow_origin)
    except ValueError as exc:
        parser.error(str(exc))
    with ConsoleWorker(args.data_dir.expanduser().resolve()) as api:
        with ConsoleServer(args.port, api, token, allowed_origins=origins) as server:
            print(f"SeekMemory console: http://127.0.0.1:{server.server_port}", flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    return 0
