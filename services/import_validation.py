"""File inspection, role validation and Source identity preflight."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

try:
    from ..app.history_import import HistoryFileError, HistoryInspection
    from ..app.history_import_limits import (
        JSONL_MAX_BYTES,
        JSONL_MAX_MESSAGES,
        JSON_MAX_BYTES,
        JSON_MAX_MESSAGES,
    )
    from ..app.ports import HistoryImportFiles, HistoryImportStore, HistoryReader
    from .import_policy import (
        RoleSelection,
        build_source_entries,
        reply_source_ids,
        resolve_roles,
    )
    from .import_utils import VALIDATION_BATCH, take
except ImportError:
    from app.history_import import HistoryFileError, HistoryInspection
    from app.history_import_limits import (
        JSONL_MAX_BYTES,
        JSONL_MAX_MESSAGES,
        JSON_MAX_BYTES,
        JSON_MAX_MESSAGES,
    )
    from app.ports import HistoryImportFiles, HistoryImportStore, HistoryReader
    from services.import_policy import (
        RoleSelection,
        build_source_entries,
        reply_source_ids,
        resolve_roles,
    )
    from services.import_utils import VALIDATION_BATCH, take


class HistoryImportError(ValueError):
    """A safe administrator-facing import validation or lifecycle error."""


@dataclass(frozen=True)
class _ValidatedStage:
    selection_hash: str
    duplicate_count: int
    skipped_count: int


def _selection_hash(selection: RoleSelection) -> str:
    encoded = json.dumps(asdict(selection), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _inspection_preview(inspection: HistoryInspection) -> dict[str, Any]:
    return {
        "format": inspection.format,
        "version": inspection.version,
        "platform": inspection.platform,
        "conversationType": inspection.conversation_type,
        "name": inspection.name,
        "members": [
            {"platformId": member.platform_id, "accountName": member.account_name}
            for member in inspection.members
        ],
        "senderCounts": inspection.sender_counts,
        "messageCount": inspection.accepted_messages,
        "messageRows": inspection.message_rows + inspection.missing_id_rows,
        "skippedCount": inspection.skipped_rows,
        "missingIdCount": inspection.missing_id_rows,
        "firstAt": inspection.first_at,
        "lastAt": inspection.last_at,
        "warnings": list(inspection.warnings),
    }


class HistoryImportValidator:
    """Validate staged files before the first immutable Source is admitted."""

    def __init__(
        self,
        *,
        imports: HistoryImportStore,
        files: HistoryImportFiles,
        reader: HistoryReader,
    ) -> None:
        self.imports = imports
        self.files = files
        self.reader = reader
        self._validated: dict[str, _ValidatedStage] = {}

    async def inspect_upload(self, stage_key: str) -> dict[str, Any]:
        """Return safe metadata for role selection."""
        staged_path = self.files.preview_path(stage_key)
        try:
            inspection = await asyncio.to_thread(self.reader.inspect, staged_path)
            byte_limit, message_limit = (
                (JSONL_MAX_BYTES, JSONL_MAX_MESSAGES)
                if inspection.format == "jsonl"
                else (JSON_MAX_BYTES, JSON_MAX_MESSAGES)
            )
            if staged_path.stat().st_size > byte_limit:
                raise HistoryImportError("文件超过该格式的安全上限")
            if inspection.message_rows + inspection.missing_id_rows > message_limit:
                raise HistoryImportError("消息条数超过该格式的安全上限")
            if inspection.missing_id_rows:
                raise HistoryImportError(
                    f"有 {inspection.missing_id_rows} 条可解析消息缺少 platformMessageId，不能导入"
                )
            return _inspection_preview(inspection)
        except (HistoryFileError, HistoryImportError):
            self.imports.clear_preflight(stage_key)
            self.files.delete(stage_key)
            raise

    async def validate_stage(
        self,
        stage_key: str,
        selection: RoleSelection,
        *,
        retained: bool = False,
    ) -> dict[str, Any]:
        """Resolve roles and preflight every Source identity before admission."""
        path = self.files.path_for_key(stage_key) if retained else self.files.preview_path(stage_key)
        self.imports.clear_preflight(stage_key)
        try:
            inspection = await asyncio.to_thread(self.reader.inspect, path)
            byte_limit, message_limit = (
                (JSONL_MAX_BYTES, JSONL_MAX_MESSAGES)
                if inspection.format == "jsonl"
                else (JSON_MAX_BYTES, JSON_MAX_MESSAGES)
            )
            if path.stat().st_size > byte_limit:
                raise HistoryImportError("文件超过该格式的安全上限")
            if inspection.message_rows + inspection.missing_id_rows > message_limit:
                raise HistoryImportError("消息条数超过该格式的安全上限")
            if inspection.missing_id_rows:
                raise HistoryImportError(
                    f"有 {inspection.missing_id_rows} 条可解析消息缺少 platformMessageId，不能导入"
                )
            roles = resolve_roles(inspection, selection)
            messages = self.reader.iter_messages_sorted(str(path))
            totals = {"unique": 0, "duplicates": 0, "existing": 0}
            valid_rows = 0
            previous = None

            while True:
                message_batch = await asyncio.to_thread(
                    take, messages, VALIDATION_BATCH
                )
                if not message_batch:
                    break
                parent_topics = self.imports.preflight_user_topics(
                    stage_key, reply_source_ids(message_batch, selection.target_umo)
                )
                entries, previous = await asyncio.to_thread(
                    build_source_entries,
                    message_batch,
                    roles=roles,
                    target_umo=selection.target_umo,
                    platform=inspection.platform,
                    previous=previous,
                    parent_topics=parent_topics,
                )
                result = self.imports.validate_sources(stage_key, entries)
                for key in totals:
                    totals[key] += int(result.get(key, 0))
                valid_rows += len(entries)
            if valid_rows != inspection.accepted_messages:
                raise HistoryImportError("预览后文件内容发生变化，请重新上传")
            duplicate_count = totals["duplicates"] + totals["existing"]
            preview = _inspection_preview(inspection)
            preview.update(
                {
                    "uniqueSourceCount": max(
                        0, totals["unique"] - totals["existing"]
                    ),
                    "duplicateCount": duplicate_count,
                    "targetUmo": selection.target_umo.strip(),
                    "roleMapping": {
                        "assistantMemberId": next(
                            key for key, value in roles.items() if value == "assistant"
                        ),
                        "userMemberId": next(
                            key for key, value in roles.items() if value == "user"
                        ),
                    },
                }
            )
            self._validated[stage_key] = _ValidatedStage(
                _selection_hash(selection), duplicate_count, inspection.skipped_rows
            )
            return preview
        except Exception as exc:
            self.imports.clear_preflight(stage_key)
            self._validated.pop(stage_key, None)
            if isinstance(exc, (HistoryFileError, HistoryImportError)):
                self.files.delete(stage_key)
            if isinstance(exc, HistoryImportError):
                raise
            if isinstance(exc, HistoryFileError):
                raise HistoryImportError(str(exc)) from exc
            if type(exc).__name__ == "SourceIdentityConflict":
                self.files.delete(stage_key)
                raise HistoryImportError("同一稳定消息 ID 对应了不同内容，文件已拒绝") from exc
            raise

    def create_task(
        self, stage_key: str, selection: RoleSelection, *, retained: bool = False
    ) -> str:
        validation = self._validated.get(stage_key)
        if validation is None or validation.selection_hash != _selection_hash(selection):
            raise HistoryImportError("请重新预览并确认角色映射")
        if retained:
            self.files.path_for_key(stage_key)
        else:
            self.files.preview_path(stage_key)
        task_id = "hi_" + uuid4().hex
        self.imports.create_task(
            task_id,
            stage_key,
            format_id="chatlab",
            duplicate_count=validation.duplicate_count,
            skipped_count=validation.skipped_count,
            selection=asdict(selection),
        )
        self._validated.pop(stage_key, None)
        self.files.release_preview(stage_key)
        return task_id

    async def retry_task(self, old_task_id: str) -> tuple[str, RoleSelection]:
        old = self.imports.task_stage(old_task_id)
        if old is None or old.get("status") not in {"failed", "partial", "interrupted"}:
            raise HistoryImportError("该任务当前不能重试")
        stage_key = str(old.get("stage_key") or "")
        if not stage_key:
            raise HistoryImportError("原文件已清理，请重新上传后发起导入")
        saved_selection = self.imports.task_selection(old_task_id)
        if not saved_selection:
            raise HistoryImportError("任务的角色确认信息已清理，请重新上传")
        try:
            selection = RoleSelection(**saved_selection)
        except TypeError as exc:
            raise HistoryImportError("任务的角色确认信息无效，请重新上传") from exc
        if old.get("stage_expires_at"):
            try:
                expires = datetime.fromisoformat(old["stage_expires_at"])
                current = datetime.now(expires.tzinfo) if expires.tzinfo else datetime.now()
                if expires <= current:
                    raise HistoryImportError("原文件已过期，请重新上传")
            except ValueError:
                raise HistoryImportError("原文件已过期，请重新上传")
        await self.validate_stage(stage_key, selection, retained=True)
        task_id = self.create_task(stage_key, selection, retained=True)
        if old.get("status") == "interrupted":
            self.imports.supersede_interrupted(old_task_id, task_id)
        else:
            self.imports.release_stage(old_task_id)
        return task_id, selection
