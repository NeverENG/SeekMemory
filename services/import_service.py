"""Public facade for administrator-initiated history initialization."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

try:
    from ..app.ports import HistoryImportFiles, HistoryImportStore, HistoryReader
    from .import_policy import RoleSelection
    from .import_runner import ImportTaskRunner
    from .import_validation import HistoryImportError, HistoryImportValidator
except ImportError:
    from app.ports import HistoryImportFiles, HistoryImportStore, HistoryReader
    from services.import_policy import RoleSelection
    from services.import_runner import ImportTaskRunner
    from services.import_validation import HistoryImportError, HistoryImportValidator


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


class ImportService:
    """Coordinate staged validation, task lifecycle and the extraction runner."""

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
        self.files = files
        self.validator = HistoryImportValidator(
            imports=imports,
            files=files,
            reader=reader,
        )
        self.runner = ImportTaskRunner(
            imports=imports,
            extraction=extraction,
            ingest=ingest,
            maintenance=maintenance,
            files=files,
            reader=reader,
            provider_for=provider_for,
            journal=journal,
            logger=logger,
            is_closing=is_closing,
        )

    async def inspect_upload(self, stage_key: str) -> dict[str, Any]:
        return await self.validator.inspect_upload(stage_key)

    async def validate_stage(
        self, stage_key: str, selection: RoleSelection, *, retained: bool = False
    ) -> dict[str, Any]:
        return await self.validator.validate_stage(
            stage_key, selection, retained=retained
        )

    def create_task(
        self, stage_key: str, selection: RoleSelection, *, retained: bool = False
    ) -> str:
        return self.validator.create_task(stage_key, selection, retained=retained)

    async def retry_task(self, old_task_id: str) -> tuple[str, RoleSelection]:
        return await self.validator.retry_task(old_task_id)

    def task(self, task_id: str) -> dict[str, Any] | None:
        return self.imports.task(task_id)

    def tasks(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.imports.list_tasks(limit)

    def cleanup(self) -> dict[str, int]:
        now = _now_iso()
        expired_tasks = self.imports.prune(now=now, retention_days=30)
        file_count = self.files.cleanup(
            retained_keys=self.imports.retained_stage_keys(now=now),
            now=datetime.now().astimezone(),
        )
        return {"tasks": expired_tasks, "files": file_count}

    def abandon(self, task_id: str) -> bool:
        stage = self.imports.task_stage(task_id)
        changed = self.imports.abandon_task(task_id)
        if changed and stage is not None:
            self.files.delete(stage.get("stage_key", ""))
        return changed

    async def run(self, task_id: str, selection: RoleSelection) -> None:
        await self.runner.run(task_id, selection)
