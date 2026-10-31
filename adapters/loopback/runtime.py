"""Compose the SDK-independent loopback memory services; no HTTP transport here.

组装本机回环服务需要的记忆用例；HTTP 与启动生命周期由适配层另行管理。
"""

from __future__ import annotations

import time
from dataclasses import asdict, is_dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from app.budget import ContextBudget
from core.domain.memory.graph import Graph
from perceive.buffer import Buffer
from recall.retriever import HybridRetriever
from services.ingest_service import IngestService
from services.recall_service import RecallService
from services.status_service import StatusService
from services.tree_service import TreeService
from store import open_store
from store.cache import Cache

HOST_CONTRACT = 1


def jsonable(value: Any) -> Any:
    """Project enums and dataclasses into JSON-compatible structures."""
    if isinstance(value, Enum):
        return value.value
    if is_dataclass(value):
        return {key: jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    return value


class _Logger:
    """ServiceLogger 的最小实现：只输出摘要，不含正文。"""

    def __init__(self, quiet: bool = False) -> None:
        self.quiet = quiet

    def info(self, message: str) -> None:
        if not self.quiet:
            print(f"[serve] {message}", flush=True)


async def _no_model(_session: str | None = None):
    """provider_for 的占位：pull-style 抽取下内核永不调用模型。"""
    raise RuntimeError("serve.py never calls a model; extraction is pull-style")


class MemoryService:
    """Own the kernel services and map protocol requests onto them."""

    def __init__(self, data_dir: Path, config: dict[str, Any] | None = None,
                 quiet: bool = False) -> None:
        data_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.data_dir = data_dir
        self.config = dict(config or {})
        self.logger = _Logger(quiet)

        self.store = open_store(str(data_dir / "memory.db"))
        self.cache = Cache(self.store.artifacts)
        self.cache.load()
        self.graph = Graph(self.store.artifacts)
        self.tree = TreeService(self.store.artifacts, self.cache)
        self.retriever = HybridRetriever(self.graph, self.cache)
        self.buffer = Buffer(str(data_dir / "pending.json"),
                             extraction=self.store.extraction)
        self.budget = ContextBudget(
            injection_chars=int(self.config.get("budget_chars", 600)),
        )

        def cfg(key: str, default: Any = None) -> Any:
            return self.config.get(key, default)

        self.owner = str(self.config.get("owner_umo", "loopback:default"))
        self.recall_service = RecallService(
            cache=self.cache,
            graph=self.graph,
            artifacts=self.store.artifacts,
            sources=self.store.sources,
            budget=self.budget,
            config=cfg,
            owner_umo=lambda: self.owner,
            hybrid_retriever=self.retriever,
            tree=self.tree,
            tree_enabled=bool(self.config.get("tree_enabled", False)),
            log=self.logger.info,
        )
        self.ingest = IngestService(
            buffer=self.buffer,
            artifacts=self.store.artifacts,
            sources=self.store.sources,
            extraction=self.store.extraction,
            cache=self.cache,
            graph=self.graph,
            journal=None,
            config=cfg,
            provider_for=_no_model,
            owner_id=lambda: self.owner,
            logger=self.logger,
        )
        self.status_service = StatusService(
            artifacts=self.store.artifacts, ledger=self.store.ledger,
        )

    # ---------- 端点 ----------
    def healthz(self) -> tuple[int, dict]:
        return 200, {
            "ok": True,
            "version": "0.1.0",
            "host_contract": HOST_CONTRACT,
            "uptime_s": round(time.time() - STARTED_AT),
        }

    def capture(self, body: dict) -> tuple[int, dict]:
        text = str(body.get("text") or "").strip()
        if not text:
            return 400, {"error": "text is required"}
        turn = self.buffer.add(
            str(body.get("subject_key") or self.owner),
            text,
            str(body.get("speaker") or body.get("sender") or ""),
            str(body.get("msg_id") or body.get("source_id") or ""),
            str(body.get("at") or ""),
            role=str(body.get("role") or "user"),
        )
        if turn is None:
            return 400, {"error": "rejected"}
        return 200, {"accepted": True, "source_id": turn.source_id}

    def recall(self, body: dict) -> tuple[int, dict]:
        subject = str(body.get("subject_key") or self.owner)
        query = str(body.get("query") or "")
        result = self.recall_service.preview(
            query,
            subject,
            bool(body.get("private", True)),
            str(body.get("speaker") or ""),
        )
        block = str(result.get("block") or "")
        visible = list(result.get("visible") or [])
        return 200, {
            "block": block,
            "chars": len(block),
            "items": [{"id": item_id} for item_id in visible],
            "info": jsonable(result.get("info") or {}),
        }

    def persona(self, query: dict) -> tuple[int, dict]:
        row = self.status_service.persona() or {}
        text = str(row.get("text") or "")
        return 200, {
            "text": text,
            "chars": len(text),
            "revision": int(row.get("revision") or 0),
        }

    def status(self) -> tuple[int, dict]:
        return 200, {
            "host_contract": HOST_CONTRACT,
            "phase": "idle",
            "progress": {"phase": "idle", "pending": 0, "running": 0},
            "ledger_valid": bool(self.status_service.ledger_valid()),
            "uptime_s": round(time.time() - STARTED_AT),
        }

    def extract_plan(self, query: dict) -> tuple[int, dict]:
        """Return idle or an honest error until a public ChatRequest plan exists.

        A list of Source IDs is not a runnable plan: DSH needs chat_request.prompt.
        """
        if not self.store.extraction.ready_extraction_ids():
            return 204, {}
        return 501, {"error": "not_implemented",
                     "detail": "pull-style plan requires a public ChatRequest API"}

    def extract_commit(self, body: dict) -> tuple[int, dict]:
        """显式未实现：内核还没有跨进程的 plan→commit 公开 API。

        现有路径是 IngestService.extract(rows, model) 在一次调用里完成
        「调模型 → build_plan → _persist_plan」。要在独立进程里做 pull-style
        提交，需要内核暴露「用宿主回传的 chat_response 持久化」的公开入口
        （内部等价于 build_plan + PreparedExtraction + _persist_plan）。
        在那之前这里返回 501，而不是伪造一个 200。
        """
        task_id = str(body.get("task_id") or "")
        if not task_id:
            return 400, {"error": "task_id is required"}
        if body.get("chat_response") is None:
            return 400, {"error": "chat_response is required"}
        return 501, {
            "error": "not_implemented",
            "detail": "pull-style commit needs a public kernel API (build_plan + persist)",
        }


STARTED_AT = time.time()
