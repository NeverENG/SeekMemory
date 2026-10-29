"""Compose a loopback runtime service with local state/audit files; own and close the HTTP listener.

组装使用本地状态及审计文件的回环运行服务，拥有并关闭 HTTP 监听端口。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from dataclasses import asdict, is_dataclass
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime import (
    AgentRuntime, EpisodeRecorder, JsonlEpisodeStore, JsonStateStore,
    MemoryContextRequest, RunRecorder, RuntimeInput,
)


def jsonable(value: Any) -> Any:
    """Project enums and data values into JSON-compatible structures.

    将枚举及数据值转换为 JSON 兼容结构。
    """
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    return value


class RuntimeService:
    """Own a local runtime and delegate protocol requests without another memory implementation.

    拥有本地运行时并委托协议请求，不另行实现记忆。
    """
    def __init__(self, data_dir: Path) -> None:
        data_dir.mkdir(parents=True, exist_ok=True)
        episodes = EpisodeRecorder(JsonlEpisodeStore(str(data_dir / "episodes.jsonl")))
        recorder = RunRecorder(
            sources=None, buffer=None, checkpoint=None, episodes=episodes
        )
        self.runtime = AgentRuntime(
            JsonStateStore(str(data_dir / "state.json")),
            clock=time.time,
            recorder=recorder,
        )

    def event(self, body: dict) -> tuple[int, dict]:
        """Map a supported event request to runtime recording; return status and JSON values.

        将受支持事件请求映射到运行时记录，返回状态及 JSON 值。
        """
        kind = str(body.get("kind") or "")
        if kind == "accept_user":
            try:
                event = RuntimeInput(**dict(body.get("input") or {}))
                receipt = self.runtime.accept_user(
                    event, event_id=str(body.get("event_id") or ""), now=time.time()
                )
                return 200, jsonable(receipt)
            except (TypeError, ValueError) as exc:
                return 400, {"error": type(exc).__name__}
        if kind == "record_reply":
            reply = self.runtime.record_reply(
                run_id=str(body.get("run_id") or ""),
                session_id=str(body.get("session_id") or ""),
                text=str(body.get("text") or ""),
                speaker_id=str(body.get("speaker_id") or ""),
                turn_id=str(body.get("turn_id") or ""),
                reply_to=str(body.get("reply_to") or ""),
                recall_ids=tuple(body.get("recall_ids") or ()),
            )
            return 200, jsonable(reply) if reply is not None else {"accepted": True}
        if kind == "record_delivery":
            self.runtime.record_delivery(
                run_id=str(body.get("run_id") or ""),
                session_id=str(body.get("session_id") or ""),
                decision=str(body.get("decision") or "reply"),
                reason=str(body.get("reason") or "delivered"),
                response_chars=int(body.get("response_chars") or 0),
                tool_calls=tuple(body.get("tool_calls") or ()),
                user_source_id=str(body.get("user_source_id") or ""),
                assistant_source_id=str(body.get("assistant_source_id") or ""),
                read_through_seq=body.get("read_through_seq"),
                now=time.time(),
            )
            return 200, {"accepted": True}
        if kind == "record_error":
            self.runtime.record_error(
                run_id=str(body.get("run_id") or ""),
                session_id=str(body.get("session_id") or ""),
                decision=str(body.get("decision") or "reply"),
                reason=str(body.get("reason") or "error"),
                error=str(body.get("error") or "host_error"),
                user_source_id=str(body.get("user_source_id") or ""),
                assistant_source_id=str(body.get("assistant_source_id") or ""),
            )
            return 200, {"accepted": True}
        if kind == "action_result":
            return 200, {"accepted": True}
        return 400, {"error": "unsupported_event"}

    def context(self, body: dict) -> tuple[int, dict]:
        """Map a context request to the runtime context port.

        将上下文请求映射到运行时上下文端口。
        """
        request = MemoryContextRequest(
            session_id=str(body.get("session_id") or ""),
            query=str(body.get("query") or body.get("value") or ""),
            source_id=str(body.get("source_id") or ""),
            speaker_id=str(body.get("speaker_id") or ""),
            private=bool(body.get("private")),
            event_time=float(body.get("event_time") or 0.0),
            received_at=float(body.get("received_at") or 0.0),
            now=float(body.get("now") or 0.0),
            reason=str(body.get("reason") or "inbound"),
        )
        context = self.runtime.build_context(request, now=request.now or time.time())
        return 200, jsonable(context)


class Handler(BaseHTTPRequestHandler):
    """Adapt authenticated loopback HTTP requests to the injected runtime service.

    将已认证回环 HTTP 请求适配到注入的运行服务。
    """
    service: RuntimeService
    token: str

    def log_message(self, *_args) -> None:
        """Suppress default access logging to avoid recording request details.

        关闭默认访问日志，避免记录请求细节。
        """
        return

    def send_json(self, status: int, payload: dict) -> None:
        """Write one JSON response with explicit length and content type.

        写入带明确长度及内容类型的一次 JSON 响应。
        """
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        """Expose health metadata and return not-found for other paths.

        提供健康元数据，其他路径返回未找到。
        """
        if self.path == "/healthz":
            self.send_json(200, {
                "ok": True,
                "version": "0.0.1-python-runtime",
                "host_contract": 1,
                "runtime_contract": 1,
                "runtime_gate_enabled": False,
            })
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self) -> None:
        """Authenticate, parse and delegate the existing event/context protocol.

        认证、解析并委托既有事件及上下文协议。
        """
        if self.headers.get("authorization") != f"Bearer {self.token}":
            self.send_json(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("content-length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except (TypeError, ValueError):
            self.send_json(400, {"error": "bad_json"})
            return
        if self.path == "/runtime/events":
            status, payload = self.service.event(body)
        elif self.path == "/runtime/context":
            status, payload = self.service.context(body)
        else:
            status, payload = 404, {"error": "not_found"}
        self.send_json(status, payload)


def main() -> int:
    """Create service/listener metadata, serve locally and close the listener even on startup-write failure.

    创建服务及监听元数据、本地服务，并在启动写入失败时仍关闭监听。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default="seekmemory-runtime-token")
    args = parser.parse_args()
    data_dir = Path(args.data_dir).expanduser().resolve()
    Handler.service = RuntimeService(data_dir)
    Handler.token = args.token
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    try:
        endpoint = {
            "port": server.server_address[1],
            "token": args.token,
            "pid": os.getpid(),
            "version": "0.0.1-python-runtime",
            "host_contract": 1,
            "runtime_contract": 1,
            "runtime_gate_enabled": False,
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        (data_dir / "runtime.json").write_text(json.dumps(endpoint), encoding="utf-8")
        server.serve_forever()
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
