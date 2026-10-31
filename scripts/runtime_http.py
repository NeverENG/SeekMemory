"""Compose a loopback runtime service with local state/audit files; own and close the HTTP listener.

组装使用本地状态及审计文件的回环运行服务，拥有并关闭 HTTP 监听端口。

本文件现在承载两个面，同一个进程、同一个数据目录：

1. **Runtime 面**（`/runtime/events`、`/runtime/context`）：原有能力，未改动；
2. **Kernel 面**（`/capture`、`/recall`、`/persona`、`/status`、`/extract/plan`）：
   直接读 `store/` 与 `recall/`，Source 落库为不可变证据。

⚠️ Kernel 面的 recall 当前是 **Source 级兜底**，不是 Artifact 级：
本服务不内建模型 provider，抽取（Source → Artifact）没有跑，所以召回先按
BM25 在最近 Source 上排序、再把命中的正文拼成有界 block。响应里的
`mode` 字段会标 `source_fallback`，接上真实抽取后应改成 `artifact`。
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import threading
import time
from dataclasses import asdict, is_dataclass
from enum import Enum
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.runtime import (
    AgentRuntime, EpisodeRecorder, JsonlEpisodeStore, JsonStateStore,
    MemoryContextRequest, RunRecorder, RuntimeInput,
)
from core.domain.memory.source import Source, make_source_id
from recall.source_query import query_recent
from store.composition import open_store

# 预算低于这个字数就老实返回空块，而不是硬塞一句
MIN_USEFUL_BUDGET = 60


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
        self.data_dir = data_dir
        # sqlite3 连接不能跨线程用；ThreadingHTTPServer 每请求一个线程，
        # 所以每个线程持有自己的连接（WAL 允许并发读）。
        self._local = threading.local()

    def _store(self):
        """Open one Store per thread and reuse it; SQLite connections are thread-bound.

        每个线程各开一个 Store 并复用；SQLite 连接与线程绑定。
        """
        store = getattr(self._local, "store", None)
        if store is None:
            store = open_store(str(self.data_dir / "memory.db"))
            self._local.store = store
        return store

    # ---------- Runtime 面 ----------
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

    # ---------- Kernel 面 ----------
    def capture(self, body: dict) -> tuple[int, dict]:
        """Append one immutable Source; never overwrites existing evidence.

        追加一条不可变原始证据；不覆盖已有证据。
        """
        subject = str(body.get("subject_key") or "")
        session = str(body.get("session") or subject)
        role = str(body.get("role") or "user")
        text = str(body.get("text") or "")
        at = str(body.get("at") or "")
        msg_id = str(body.get("msg_id") or "")
        if not text.strip():
            return 400, {"error": "empty_text"}
        source_id = make_source_id(
            event_id=msg_id, session_id=session, speaker_id=subject,
            role=role, text=text, at=at,
        )
        source = Source(
            id=source_id, turn_id="", session_id=session, speaker_id=subject,
            role=role, text=text, at=at,
        )
        try:
            written = self._store().sources.append_sources([source])
        except ValueError as exc:
            return 400, {"error": type(exc).__name__}
        return 200, {"source_id": source_id, "written": int(written)}

    def recall(self, body: dict) -> tuple[int, dict]:
        """Rank recent Source evidence and assemble a bounded block.

        对近期原始证据排序并组装有界上下文块。
        """
        subject = str(body.get("subject_key") or "")
        query = str(body.get("query") or "")
        budget = max(0, int(body.get("budget_chars") or 0))
        k = max(1, int(body.get("k") or 8))
        hours = max(1, int(body.get("hours") or 72))

        since = (datetime.datetime.now() - datetime.timedelta(hours=hours)).isoformat(timespec="seconds")
        recent = self._store().sources.recent_sources(since=since, limit=500)
        # 只看这个主体的证据
        recent = [item for item in recent if item.speaker_id == subject] or recent

        hits = query_recent(query, recent, session_id="", speaker=subject, limit=200) if recent else []
        pool = self._store().sources.sources_by_ids([hit.source_id for hit in hits]) if hits else {}
        ordered = [pool[hit.source_id] for hit in hits if hit.source_id in pool]

        items = [
            {"source_id": item.id, "text": item.text}
            for item in ordered[:k]
            if str(item.text or "").strip()
        ]

        block = ""
        if budget >= MIN_USEFUL_BUDGET:
            parts: list[str] = []
            used = 0
            for item in items:
                piece = item["text"].strip()
                if used + len(piece) > budget:
                    continue
                parts.append(piece)
                used += len(piece)
            block = "".join(parts)

        return 200, {
            "mode": "source_fallback",
            "subject_key": subject,
            "items": items if block else [],
            "block": block,
            "budget_chars": budget,
            "candidates": len(recent),
        }

    def persona(self, query: dict) -> tuple[int, dict]:
        """Report the active persona revision; seed-only until Dream runs.

        返回当前人格版本；在 Dream 跑过之前只有种子版本。
        """
        subject = (query.get("subject_key") or [""])[0]
        return 200, {
            "subject_key": subject,
            "revision": 0,
            "text": "",
            "chain": [],
            "note": "seed-only: Dream 尚未产生人格修订",
        }

    def status(self) -> tuple[int, dict]:
        """Report contract version plus coarse progress counters.

        返回契约版本与粗粒度进度计数。
        """
        try:
            sources = len(self._store().sources.recent_sources(since="1970-01-01T00:00:00", limit=100000))
        except Exception:  # noqa: BLE001 - 状态查询不应拖垮服务
            sources = -1
        return 200, {
            "ok": True,
            "host_contract": 1,
            "runtime_contract": 1,
            "progress": {
                "phase": "idle",
                "sources": sources,
                "queued_extractions": 0,
                "persona_revision": 0,
            },
            "degraded": {
                "recall": "source_fallback",
                "extractor": "not_configured",
            },
        }

    def extract_plan(self) -> tuple[int, dict]:
        """Return 204 when no extractor is configured; there is nothing to plan.

        未配置抽取器时返回 204：没有可排的活。
        """
        return 204, {}

    def close(self) -> None:
        """Close this thread's owned SQLite connection if it was opened.

        关闭当前线程自有的 SQLite 连接（若已打开）。
        """
        try:
            store = getattr(self._local, "store", None)
            if store is not None:
                store.close()
                self._local.store = None
        except Exception:  # noqa: BLE001 - 退出路径不抛
            pass


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
        if status != 204:
            self.wfile.write(data)

    def authorized(self) -> bool:
        """Check the loopback bearer token.

        校验回环 bearer token。
        """
        return self.headers.get("authorization") == f"Bearer {self.token}"

    def do_GET(self) -> None:
        """Serve health (open) and the authenticated kernel reads.

        提供健康检查（不鉴权）以及需鉴权的内核读取。
        """
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/healthz":
            self.send_json(200, {
                "ok": True,
                "version": "0.0.1-python-runtime",
                "host_contract": 1,
                "runtime_contract": 1,
                "kernel_contract": 1,
                "runtime_gate_enabled": False,
            })
            return
        if not self.authorized():
            self.send_json(401, {"error": "unauthorized"})
            return
        if path == "/status":
            status, payload = self.service.status()
        elif path == "/persona":
            status, payload = self.service.persona(parse_qs(parsed.query))
        elif path == "/extract/plan":
            status, payload = self.service.extract_plan()
        else:
            status, payload = 404, {"error": "not_found"}
        self.send_json(status, payload)

    def do_POST(self) -> None:
        """Authenticate, parse and delegate the event/context/kernel protocols.

        认证、解析并委托事件、上下文及内核协议。
        """
        if not self.authorized():
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
        elif self.path == "/capture":
            status, payload = self.service.capture(body)
        elif self.path == "/recall":
            status, payload = self.service.recall(body)
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
    service = RuntimeService(data_dir)
    Handler.service = service
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
            "kernel_contract": 1,
            "runtime_gate_enabled": False,
            "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        (data_dir / "runtime.json").write_text(json.dumps(endpoint), encoding="utf-8")
        server.serve_forever()
    finally:
        server.server_close()
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
