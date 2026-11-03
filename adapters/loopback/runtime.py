"""Compose the SDK-independent loopback memory services; no HTTP transport here.

组装本机回环服务需要的记忆用例；HTTP 与启动生命周期由适配层另行管理。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from app.budget import ContextBudget
from core.domain.memory.graph import Graph
from perceive.buffer import Buffer
from recall.retriever import HybridRetriever
from services.ingest_service import IngestService
from services.management_service import ManagementService
from services.recall_service import RecallService
from services.status_service import StatusService
from services.persona_evolution_service import PersonaEvolutionService
from services.persona_proposals import sentence_diff
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
        self.tasks: dict[str, Any] = {}
        self.status_service = StatusService(
            artifacts=self.store.artifacts, ledger=self.store.ledger,
        )
        self.management_service = ManagementService(
            self.store.artifacts, self.store.sources, self.store.ledger,
            self.cache, self.recall_service,
        )
        self.persona_evolution = PersonaEvolutionService(
            self.store.artifacts, self.store.sources, self.cache,
            min_interval_s=float(self.config.get("persona_min_interval_s", 30.0)),
            proposals=self.store.persona_proposals,
            subject_key=lambda: self.owner,
        )

    def _same_subject(self, requested: Any) -> bool:
        """One database owns one logical subject; hosts may share its stable key.

        一个数据库只属于一个逻辑主体；多个宿主可以共用该稳定键。
        """
        return not requested or str(requested) == self.owner

    # ---------- 端点 ----------
    def healthz(self) -> tuple[int, dict]:
        return 200, {
            "ok": True,
            "version": "0.1.0",
            "host_contract": HOST_CONTRACT,
            "uptime_s": round(time.time() - STARTED_AT),
        }

    def capture(self, body: dict) -> tuple[int, dict]:
        if not self._same_subject(body.get("subject_key")):
            return 403, {"error": "subject_mismatch"}
        text = str(body.get("text") or "").strip()
        if not text:
            return 400, {"error": "text is required"}
        turn = self.buffer.add(
            str(body.get("subject_key") or self.owner),
            text,
            str(body.get("speaker") or body.get("sender") or ""),
            str(body.get("msg_id") or body.get("source_id") or ""),
            str(body.get("at") or ""),
            reply_to=str(body.get("reply_to") or ""),
            role=str(body.get("role") or "user"),
        )
        if turn is None:
            return 400, {"error": "rejected"}
        return 200, {"accepted": True, "source_id": turn.source_id}

    def recall(self, body: dict) -> tuple[int, dict]:
        if not self._same_subject(body.get("subject_key")):
            return 403, {"error": "subject_mismatch"}
        subject = str(body.get("subject_key") or self.owner)
        query = str(body.get("query") or "")
        try:
            budget = int(body["budget_chars"]) if body.get("budget_chars") is not None else None
            k = int(body["k"]) if body.get("k") is not None else None
        except (TypeError, ValueError):
            return 400, {"error": "invalid_recall_limit"}
        if budget is not None and budget < 0 or k is not None and k < 1:
            return 400, {"error": "invalid_recall_limit"}
        result = self.recall_service.preview(
            query,
            subject,
            bool(body.get("private", True)),
            str(body.get("speaker") or ""),
            budget_chars_override=budget, recall_k_override=k,
        )
        block = str(result.get("block") or "")
        info = dict(result.get("info") or {})
        # Loose-mode recall can use an internal 1.4x narrative allowance; an
        # explicit host budget is still an unconditional transport limit.
        # 宽松召回可内部扩充叙述空间，但宿主显式预算始终是硬上限。
        if budget is not None and len(block) > budget:
            block = ""
            info["final_ids"] = []
            info["chars"] = 0
        return 200, {
            "block": block,
            "chars": len(block),
            "items": [{"id": item_id} for item_id in info.get("final_ids", ())] if block else [],
            "info": jsonable(info),
        }

    def persona(self, query: dict) -> tuple[int, dict]:
        if not self._same_subject(query.get("subject_key")):
            return 403, {"error": "subject_mismatch"}
        row = self.status_service.persona() or {}
        text = str(row.get("text") or "")
        return 200, {
            "text": text,
            "chars": len(text),
            "revision": int(row.get("revision") or 0),
        }

    def persona_write(self, body: dict) -> tuple[int, dict]:
        """Commit an authored revision and append a content-free audit record."""
        if not isinstance(body, dict):
            return 400, {"error": "invalid_body"}
        if not self._same_subject(body.get("subject_key")):
            return 403, {"error": "subject_mismatch"}
        raw_text = body.get("text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            return 400, {"error": "text is required"}
        text = raw_text.strip()
        if len(text) > 2000:
            return 400, {"error": "text is too long"}
        note = body.get("note", "")
        if not isinstance(note, str) or len(note.strip()) > 300:
            return 400, {"error": "invalid_note"}

        active = self.cache.active("persona")
        current = max(active, key=lambda art: art.header.revision) if active else None
        history = self.store.artifacts.history(current.header.id) if current else []
        seed = next((row["payload"] for row in reversed(history)
                     if isinstance(row.get("payload"), dict)
                     and row["payload"].get("origin") == "seed"), {})
        reference = seed or (current.payload if current else {})
        corpus = next((row["payload"]["corpus"] for row in reversed(history)
                       if isinstance(row.get("payload"), dict)
                       and isinstance(row["payload"].get("corpus"), list)
                       and row["payload"]["corpus"]), [])
        authored = {
            "id": reference.get("seed_id") or "self-authored",
            "version": reference.get("seed_version") or "1.0.0",
            "name": reference.get("persona_name") or "自我",
            "persona": text,
            "style": reference.get("style") or {},
            "boundaries": reference.get("boundaries") or [],
            "license": reference.get("seed_license") or "",
            "source": "self-authored via persona_write",
            "content_rating": reference.get("content_rating") or "general",
            "locale": reference.get("locale") or "zh-CN",
        }
        if corpus:
            authored["corpus"] = corpus
        with (self.data_dir / "persona-writes.log").open("a", encoding="utf-8") as audit:
            result = self.management_service.bootstrap_persona(authored)
            record = {"at": datetime.now(timezone.utc).isoformat(),
                      "revision": result["revision"], "chars": len(text),
                      "note": note.strip()}
            audit.write(json.dumps(record, ensure_ascii=False) + "\n")
            audit.flush()
            os.fsync(audit.fileno())
        return 200, {"revision": result["revision"], "chars": len(text)}

    def _proposal_subject(self, body: dict) -> tuple[int, dict] | None:
        if not isinstance(body, dict):
            return 400, {"error": "invalid_body"}
        key = body.get("subject_key")
        if not isinstance(key, str) or not key.strip():
            return 400, {"error": "subject_key_required"}
        if not self._same_subject(key):
            return 403, {"error": "subject_mismatch"}
        return None

    def persona_proposals(self, query: dict) -> tuple[int, dict]:
        denied = self._proposal_subject(query)
        if denied is not None:
            return denied
        status = query.get("status", "pending")
        if status not in ("pending", "approved", "rejected", "expired", "applying"):
            return 400, {"error": "invalid_proposal_status"}
        rows = self.store.persona_proposals.list_status(query["subject_key"], status)
        return 200, {"proposals": rows}

    def _proposal_target(self, proposal_id: str, body: dict):
        denied = self._proposal_subject(body)
        if denied is not None:
            return denied, None
        row = self.store.persona_proposals.get(body["subject_key"], proposal_id)
        if row is None:
            return (404, {"error": "proposal_not_found"}), None
        if row["status"] == "expired":
            return (410, {"error": "proposal_expired"}), None
        if row["status"] != "pending":
            error = "already_approved" if row["status"] == "approved" else "proposal_processed"
            return (409, {"error": error}), None
        if row["expires_at"]:
            try:
                until = datetime.fromisoformat(row["expires_at"])
                if until.tzinfo is None:
                    until = until.replace(tzinfo=timezone.utc)
                expired = until <= datetime.now(timezone.utc)
            except ValueError:
                expired = True  # Corrupt expiry fails closed.
            if expired:
                self.store.persona_proposals.transition(
                    body["subject_key"], proposal_id, "pending", "expired"
                )
                return (410, {"error": "proposal_expired"}), None
        return None, row

    def persona_proposal_approve(self, proposal_id: str, body: dict) -> tuple[int, dict]:
        denied, row = self._proposal_target(proposal_id, body)
        if denied is not None:
            return denied
        actor = body.get("actor")
        if body.get("confirmed") is not True or actor not in ("self", "owner"):
            return 400, {"error": "explicit_approval_required"}
        active = self.cache.active("persona")
        current = max(active, key=lambda art: art.header.revision) if active else None
        current_id = current.header.id if current else ""
        current_revision = int(current.header.revision) if current else 0
        current_text = str(current.payload.get("text") or "") if current else ""
        if (row["persona_id"] != current_id or row["base_revision"] != current_revision
                or row["old_text"] != current_text):
            return 409, {"error": "stale_persona"}
        if not self.store.persona_proposals.transition(
                body["subject_key"], proposal_id, "pending", "applying", actor=actor):
            return 409, {"error": "proposal_processed"}
        # A failed audit fsync may follow a successful persona commit.  Keep the
        # applying marker for manual reconciliation; never replay that write.
        code, result = self.persona_write({
            "subject_key": body["subject_key"], "text": row["new_text"],
            "note": f"proposal:{proposal_id} actor:{actor}",
        })
        if code != 200:
            return code, result
        if not self.store.persona_proposals.transition(
                body["subject_key"], proposal_id, "applying", "approved",
                actor=actor, revision=result["revision"]):
            return 500, {"error": "approval_state_failed"}
        return 200, {"id": proposal_id, "status": "approved",
                     "revision": result["revision"]}

    def persona_proposal_reject(self, proposal_id: str, body: dict) -> tuple[int, dict]:
        denied, _row = self._proposal_target(proposal_id, body)
        if denied is not None:
            return denied
        actor = body.get("actor")
        if body.get("confirmed") is not True or actor not in ("self", "owner"):
            return 400, {"error": "explicit_rejection_required"}
        if not self.store.persona_proposals.transition(
                body["subject_key"], proposal_id, "pending", "rejected", actor=actor):
            return 409, {"error": "proposal_processed"}
        return 200, {"id": proposal_id, "status": "rejected"}

    def persona_proposal_revise(self, proposal_id: str, body: dict) -> tuple[int, dict]:
        denied, row = self._proposal_target(proposal_id, body)
        if denied is not None:
            return denied
        new_text = body.get("new_text")
        if not isinstance(new_text, str) or not new_text.strip() or len(new_text.strip()) > 2000:
            return 400, {"error": "invalid_proposal_text"}
        new_text = new_text.strip()
        try:
            diff = sentence_diff(row["old_text"], new_text)
        except ValueError:
            return 400, {"error": "invalid_proposal_text"}
        if not self.store.persona_proposals.revise(
                body["subject_key"], proposal_id, new_text, diff):
            return 409, {"error": "proposal_processed"}
        return 200, {"id": proposal_id, "status": "pending", "diff": diff}

    def status(self) -> tuple[int, dict]:
        return 200, {
            "host_contract": HOST_CONTRACT,
            "phase": "idle",
            "progress": {"phase": "idle", "pending": len(self.buffer.items), "running": 0},
            "persona_maintenance": {
                "dirty": self.persona_evolution.dirty,
                "degraded": self.persona_evolution.degraded,
                "failures": self.persona_evolution.failures,
                "last_error": self.persona_evolution.last_error,
                # A legal no-op must still say why: per-category observation
                # counts versus the unchanged MIN_EVIDENCE gate.
                **self.persona_evolution.diagnostics(),
            },
            "ledger_valid": bool(self.status_service.ledger_valid()),
            "uptime_s": round(time.time() - STARTED_AT),
        }

    def extract_plan(self, query: dict) -> tuple[int, dict]:
        """Issue a bounded, in-process task without invoking the model / 生成限量任务，模型由宿主调用。"""
        if not self._same_subject(query.get("subject_key")):
            return 403, {"error": "subject_mismatch"}
        self.persona_evolution.maybe_run()
        if self.tasks:
            task = next(iter(self.tasks.values()))
            if query.get("subject_key") and task.session_id != str(query["subject_key"]):
                return 204, {}
        else:
            task = self.ingest.next_extraction_task(
                subject_key=self.owner,
            )
            if task is None:
                return 204, {}
            self.tasks[task.task_id] = task
        return 200, {
            "task_id": task.task_id,
            "source_ids": list(task.source_ids),
            "session_id": task.session_id,
            "topic_id": task.topic_id,
            "turns": task.turns,
            "chat_request": {
                "system_prompt": task.system_prompt,
                "prompt": task.prompt,
                # Hosts that enable provider-side reasoning share this budget with the answer:
                # 800 was routinely exhausted before any JSON came out (llm_empty / http_422).
                "max_tokens": int(self.config.get("extract_max_tokens", 800)),
                "temperature": 0,
            },
        }

    def extract_commit(self, body: dict) -> tuple[int, dict]:
        """Accept only this process's issued task; preserve unfinished writes for retry."""
        task_id = str(body.get("task_id") or "")
        task = self.tasks.get(task_id)
        if task is None:
            return 409, {"error": "task_stale"}
        if "source_ids" in body and body["source_ids"] != list(task.source_ids):
            return 409, {"error": "task_stale"}
        response = body.get("chat_response")
        if not isinstance(response, dict) or not isinstance(response.get("text"), str) or not response["text"].strip():
            return 400, {"error": "chat_response.text is required"}
        try:
            usage = (int(response.get("usage_in") or 0), int(response.get("usage_cached") or 0),
                     int(response.get("usage_out") or 0))
        except (TypeError, ValueError):
            return 400, {"error": "invalid_usage"}
        try:
            outcome = self.ingest.commit_extraction(task.source_ids, response["text"], usage=usage)
        except Exception:
            self.tasks.pop(task_id, None)
            return 422, {"error": "invalid_extraction", "retryable": True}
        if "task_stale" in outcome.errors:
            self.tasks.pop(task_id, None)
            return 409, {"error": "task_stale"}
        if outcome.retryable:
            return 503, {"error": "writeback_pending", "retryable": True}
        self.tasks.pop(task_id, None)
        if outcome.written > 0:
            try:
                self.persona_evolution.after_extraction()
            except Exception as exc:
                # Maintenance never turns a successful extraction into a 500,
                # but the reason must stay visible in /status.
                self.persona_evolution.record_failure(exc)
        return 200, {"written": outcome.written, "skipped": outcome.skipped,
                     "ids": list(outcome.ids), "errors": list(outcome.errors), "retryable": False}


STARTED_AT = time.time()
