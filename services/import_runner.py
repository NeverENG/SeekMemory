"""Run one admitted history task through extraction and persona maintenance."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

try:
    from ..app.contracts import DialogueTurn
    from ..app.flush_policy import chunk_turns
    from ..app.ports import HistoryImportFiles, HistoryImportStore, HistoryReader
    from ..core.source import SourceQueueEntry
    from ..perceive.model import ProviderChatModel
    from .import_policy import (
        RoleSelection,
        TopicCorrection,
        iter_source_entries,
        reply_targets,
        resolve_roles,
    )
    from .import_utils import VALIDATION_BATCH, take
except ImportError:
    from app.contracts import DialogueTurn
    from app.flush_policy import chunk_turns
    from app.ports import HistoryImportFiles, HistoryImportStore, HistoryReader
    from core.source import SourceQueueEntry
    from perceive.model import ProviderChatModel
    from services.import_policy import (
        RoleSelection,
        TopicCorrection,
        iter_source_entries,
        reply_targets,
        resolve_roles,
    )
    from services.import_utils import VALIDATION_BATCH, take

IMPORT_TOPIC_CHUNK = 120
EXTRACTION_MAX_ATTEMPTS = 5


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ImportTaskRunner:
    """Own task admission, per-topic extraction retries and terminal state."""

    def __init__(
        self,
        *,
        imports: HistoryImportStore,
        extraction,
        ingest,
        maintenance,
        files: HistoryImportFiles,
        reader: HistoryReader,
        provider_for,
        journal,
        logger: logging.Logger,
        is_closing=lambda: False,
    ) -> None:
        self.imports = imports
        self.extraction = extraction
        self.ingest = ingest
        self.maintenance = maintenance
        self.files = files
        self.reader = reader
        self.provider_for = provider_for
        self.journal = journal
        self.logger = logger
        self.is_closing = is_closing

    async def run(self, task_id: str, selection: RoleSelection) -> None:
        stage = self.imports.task_stage(task_id)
        stage_key = str(stage.get("stage_key") or "") if stage else ""
        self.imports.set_status(task_id, "running")
        errors: set[str] = set()
        persona_status = "pending"
        retain_stage = False
        try:
            path = self.files.path_for_key(stage_key)
            inspection = await asyncio.to_thread(self.reader.inspect, path)
            roles = resolve_roles(inspection, selection)
            referenced = await asyncio.to_thread(reply_targets, str(path), self.reader)
            batch: list[SourceQueueEntry] = []
            entries = iter_source_entries(
                str(path),
                self.reader,
                roles=roles,
                target_umo=selection.target_umo,
                platform=inspection.platform,
                referenced_ids=referenced,
            )
            while True:
                items = await asyncio.to_thread(take, entries, VALIDATION_BATCH)
                if not items:
                    break
                for item in items:
                    if isinstance(item, TopicCorrection):
                        continue
                    batch.append(item)
                    if len(batch) >= VALIDATION_BATCH:
                        self.imports.admit_sources(task_id, batch, stage_key=stage_key)
                        batch = []
            if batch:
                self.imports.admit_sources(task_id, batch, stage_key=stage_key)

            await self._extract_task(task_id, errors)
            counts = self.imports.counts(task_id)
            persona = await self.maintenance.import_persona_update()
            persona_status = str(persona.get("status") or "unchanged")
            skipped = int((self.imports.task(task_id) or {}).get("skipped_count", 0))
            status = "partial" if counts["failed"] or skipped else "completed"
            retain_stage = counts["failed"] > 0
            final_counts = self.imports.finish_task(
                task_id,
                status,
                persona_status=persona_status,
                error_types=sorted(errors),
                retain_stage=retain_stage,
            )
            self.journal.record(
                "history_import",
                status,
                "ChatLab history initialization finished",
                task_id,
                context={
                    "sources": final_counts["extracted"] + final_counts["failed"],
                    "extracted": final_counts["extracted"],
                    "failed": final_counts["failed"],
                    "persona": persona_status,
                },
            )
            if not retain_stage:
                self.files.delete(stage_key)
        except asyncio.CancelledError:
            if self.is_closing():
                self.imports.set_status(task_id, "interrupted")
                self.journal.record(
                    "history_import",
                    "interrupted",
                    "ChatLab history initialization interrupted by host shutdown",
                    task_id,
                )
            else:
                self.imports.finish_task(
                    task_id,
                    "cancelled",
                    persona_status=persona_status,
                    error_types=sorted(errors),
                )
                self.files.delete(stage_key)
            raise
        except Exception as exc:
            errors.add(type(exc).__name__)
            try:
                try:
                    self.files.path_for_key(stage_key)
                    retain_stage = True
                except Exception:
                    retain_stage = False
                self.imports.finish_task(
                    task_id,
                    "failed",
                    persona_status="failed" if persona_status == "pending" else persona_status,
                    error_types=sorted(errors),
                    retain_stage=retain_stage,
                )
            except Exception as finish_error:
                self.logger.error(
                    "[seekmemory] history import task finalization failed: %s",
                    type(finish_error).__name__,
                )
            self.journal.record(
                "history_import",
                "failed",
                "ChatLab history initialization failed",
                task_id,
                error=exc,
                context={"errorType": type(exc).__name__},
            )
            if not retain_stage:
                self.files.delete(stage_key)

    async def _extract_task(self, task_id: str, errors: set[str]) -> None:
        while True:
            counts = self.imports.counts(task_id)
            if counts["pending"] == 0:
                return
            now = _now_iso()
            topic_id = self.imports.next_ready_topic(task_id, now=now)
            if not topic_id:
                next_at = self.imports.next_attempt_at(task_id)
                if not next_at:
                    raise RuntimeError("import_queue_state_unavailable")
                try:
                    retry_at = datetime.fromisoformat(next_at)
                    current = datetime.now(retry_at.tzinfo) if retry_at.tzinfo else datetime.now()
                    wait = max(0.25, (retry_at - current).total_seconds())
                except ValueError:
                    wait = 1.0
                await asyncio.sleep(min(wait, 60.0))
                continue
            rows = self.imports.topic_sources(
                task_id, topic_id, limit=IMPORT_TOPIC_CHUNK + 1, now=now
            )
            if not rows:
                continue
            turns = [
                DialogueTurn(
                    str(row["session_id"]),
                    str(row["speaker_id"]),
                    str(row["role"]),
                    str(row["text"]),
                    str(row["at"]),
                    str(row["source_id"]),
                    str(row["topic_id"]),
                    str(row["turn_id"]),
                    str(row["reply_to"] or "") or None,
                )
                for row in rows
            ]
            chunk = chunk_turns(turns, IMPORT_TOPIC_CHUNK)[0]
            source_ids = [turn.source_id for turn in chunk if turn.source_id]
            try:
                provider = await self.provider_for(chunk[0].session_id or None)
                if provider is None:
                    raise RuntimeError("ProviderUnavailable")
                outcome = await self.ingest.extract(
                    chunk,
                    ProviderChatModel(provider),
                    strict=True,
                    require_evidence=True,
                )
                if outcome.model_failed or outcome.retryable:
                    raise RuntimeError("ExtractionRetryable")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                error_type = type(exc).__name__
                errors.add(error_type)
                self.extraction.mark_extraction_failed(
                    source_ids,
                    error_type,
                    max_attempts=EXTRACTION_MAX_ATTEMPTS,
                )
                self.journal.record(
                    "history_import",
                    "warning",
                    "A historical topic extraction attempt failed",
                    task_id,
                    context={"messages": len(source_ids), "errorType": error_type},
                )
                continue
            self.extraction.mark_extraction_succeeded(source_ids)
