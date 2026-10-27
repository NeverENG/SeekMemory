"""Private bounded staging for administrator-supplied ChatLab files."""

from __future__ import annotations

import inspect
import re
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

try:
    from ..app.history_import_limits import (
        JSONL_MAX_BYTES,
        JSONL_MAX_MESSAGES,
        JSON_MAX_BYTES,
        JSON_MAX_MESSAGES,
        PREVIEW_TTL_SECONDS,
        STAGING_MAX_BYTES,
    )
except ImportError:
    from app.history_import_limits import (
        JSONL_MAX_BYTES,
        JSONL_MAX_MESSAGES,
        JSON_MAX_BYTES,
        JSON_MAX_MESSAGES,
        PREVIEW_TTL_SECONDS,
        STAGING_MAX_BYTES,
    )
_STAGE_KEY = re.compile(r"^[0-9a-f]{32}$")


class ImportFileError(ValueError):
    """A staged upload could not be accepted under the configured bounds."""


@dataclass(frozen=True)
class StagedUpload:
    key: str
    filename: str
    extension: str
    size: int
    created_at: str
    path: Path


class ImportFileStore:
    """Own opaque filenames, private permissions, quotas and file retention."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.previews: dict[str, StagedUpload] = {}
        self._upload_lock = asyncio.Lock()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass

    @staticmethod
    def _limits(extension: str) -> tuple[int, int]:
        return (
            (JSONL_MAX_BYTES, JSONL_MAX_MESSAGES)
            if extension == ".jsonl"
            else (JSON_MAX_BYTES, JSON_MAX_MESSAGES)
        )

    def _disk_usage(self) -> int:
        total = 0
        for path in self.root.iterdir():
            try:
                if path.is_file() and not path.is_symlink():
                    total += path.stat().st_size
            except OSError:
                continue
        return total

    async def save_upload(self, upload: object) -> StagedUpload:
        filename = str(getattr(upload, "filename", "") or "upload")
        suffix = Path(filename).suffix.lower()
        if suffix not in {".json", ".jsonl"}:
            raise ImportFileError("文件扩展名必须是 .json 或 .jsonl")
        per_file_limit, _ = self._limits(suffix)
        key = uuid4().hex
        target = self.root / f"{key}{suffix}"
        saver = getattr(upload, "save", None)
        if not callable(saver):
            raise ImportFileError("上传对象不支持安全暂存")
        async with self._upload_lock:
            announced = getattr(upload, "size", None)
            try:
                announced_bytes = int(announced) if announced is not None else None
            except (TypeError, ValueError):
                announced_bytes = None
            if announced_bytes is not None:
                if announced_bytes < 0 or announced_bytes > per_file_limit:
                    raise ImportFileError("文件超过该格式的上传上限")
                if self._disk_usage() + announced_bytes > STAGING_MAX_BYTES:
                    raise ImportFileError("暂存空间不足，请先清理过期导入文件")
            try:
                result = saver(target)
                if inspect.isawaitable(result):
                    await result
                target.chmod(0o600)
                size = target.stat().st_size
                if size <= 0:
                    raise ImportFileError("上传文件为空")
                if size > per_file_limit:
                    raise ImportFileError("文件超过该格式的上传上限")
                if self._disk_usage() > STAGING_MAX_BYTES:
                    raise ImportFileError("暂存空间不足，请先清理过期导入文件")
            except Exception:
                target.unlink(missing_ok=True)
                raise
        record = StagedUpload(
            key=key,
            filename=Path(filename).name[:255],
            extension=suffix,
            size=size,
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            path=target,
        )
        self.previews[key] = record
        return record

    def get_preview(self, key: str) -> StagedUpload:
        value = str(key or "")
        record = self.previews.get(value)
        if not _STAGE_KEY.fullmatch(value) or record is None:
            raise ImportFileError("预览已过期或不存在，请重新上传")
        if not record.path.is_file():
            self.previews.pop(value, None)
            raise ImportFileError("暂存文件已过期，请重新上传")
        return record

    def preview_path(self, key: str) -> Path:
        return self.get_preview(key).path

    def path_for_key(self, key: str) -> Path:
        value = str(key or "")
        if not _STAGE_KEY.fullmatch(value):
            raise ImportFileError("导入文件不存在或已过期")
        for suffix in (".json", ".jsonl"):
            path = self.root / f"{value}{suffix}"
            if path.is_file() and not path.is_symlink():
                return path
        raise ImportFileError("导入文件不存在或已过期")

    def release_preview(self, key: str) -> None:
        self.previews.pop(str(key or ""), None)

    def delete(self, key: str) -> None:
        value = str(key or "")
        self.previews.pop(value, None)
        if not _STAGE_KEY.fullmatch(value):
            return
        for suffix in (".json", ".jsonl"):
            (self.root / f"{value}{suffix}").unlink(missing_ok=True)

    def cleanup(self, *, retained_keys: set[str], now: datetime | None = None) -> int:
        current = now or datetime.now(timezone.utc)
        removed = 0
        for path in self.root.iterdir():
            if not path.is_file() or path.is_symlink():
                continue
            key = path.stem
            if not _STAGE_KEY.fullmatch(key) or key in retained_keys:
                continue
            try:
                age = current.timestamp() - path.stat().st_mtime
            except OSError:
                continue
            if age < PREVIEW_TTL_SECONDS:
                continue
            path.unlink(missing_ok=True)
            self.previews.pop(key, None)
            removed += 1
        for key, record in list(self.previews.items()):
            try:
                age = current.timestamp() - record.path.stat().st_mtime
            except OSError:
                age = PREVIEW_TTL_SECONDS + 1
            if key not in retained_keys and age >= PREVIEW_TTL_SECONDS:
                self.delete(key)
                removed += 1
        return removed
