"""Read-only ChatLab v0.0.2 JSON and JSONL format adapter."""

from __future__ import annotations

import datetime as dt
import heapq
import json
import math
import struct
import tempfile
from collections import Counter
from pathlib import Path
from typing import Iterator

try:
    from ..app.history_import import (
        HistoryFileError,
        HistoryInspection as ChatLabInspection,
        HistoryMember as ChatLabMember,
        HistoryMessage as ChatLabMessage,
    )
except ImportError:
    from app.history_import import (
        HistoryFileError,
        HistoryInspection as ChatLabInspection,
        HistoryMember as ChatLabMember,
        HistoryMessage as ChatLabMessage,
    )

CHATLAB_VERSION = "0.0.2"
MAX_PREVIEW_WARNINGS = 50
SORT_RUN_RECORDS = 50_000
_SORT_RECORD = struct.Struct(">dQQIQ")


class ChatLabFormatError(HistoryFileError):
    """A file-level error that makes a ChatLab export unsafe to import."""


class ChatLabIdentityError(ChatLabFormatError):
    """A parseable message has no stable platform message identity."""


def _text_id(value: object) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    if isinstance(value, (str, int)):
        return str(value).strip()
    return ""


def _header(chatlab: object, meta: object) -> tuple[str, str, str, str]:
    if not isinstance(chatlab, dict) or str(chatlab.get("version") or "") != CHATLAB_VERSION:
        raise ChatLabFormatError("仅支持 ChatLab v0.0.2")
    if not isinstance(meta, dict):
        raise ChatLabFormatError("缺少 ChatLab meta 元数据")
    platform = str(meta.get("platform") or "").strip()
    kind = str(meta.get("type") or "").strip()
    name = str(meta.get("name") or "").strip()
    if not platform or not name or kind not in {"private", "group"}:
        raise ChatLabFormatError("ChatLab meta 字段无效")
    if kind != "private":
        raise ChatLabFormatError("首版只接受私聊记录")
    return CHATLAB_VERSION, platform, kind, name


def _members(rows: object) -> dict[str, ChatLabMember]:
    if rows is None:
        return {}
    if not isinstance(rows, list):
        raise ChatLabFormatError("ChatLab members 必须是数组")
    result: dict[str, ChatLabMember] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ChatLabFormatError("ChatLab 成员结构无效")
        platform_id = _text_id(row.get("platformId"))
        if not platform_id:
            raise ChatLabFormatError("ChatLab 成员缺少 platformId")
        member = ChatLabMember(platform_id, str(row.get("accountName") or ""))
        old = result.get(platform_id)
        if old is not None and old != member:
            raise ChatLabFormatError("ChatLab 成员 platformId 冲突")
        result[platform_id] = member
    return result


def _at(timestamp: object) -> tuple[float, str] | None:
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return None
    value = float(timestamp)
    if not math.isfinite(value):
        return None
    try:
        moment = dt.datetime.fromtimestamp(value, tz=dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    precision = "microseconds" if moment.microsecond else "seconds"
    return value, moment.isoformat(timespec=precision)


def _message(
    row: object,
    row_number: int,
    ordinal: int,
    byte_offset: int = 0,
    byte_length: int = 0,
) -> ChatLabMessage | None:
    if not isinstance(row, dict):
        return None
    message_id = _text_id(row.get("platformMessageId"))
    # An object classified as a message is parseable even when its other
    # fields are damaged; do not invent identity from body or row position.
    if not message_id:
        raise ChatLabIdentityError(f"第 {row_number} 行消息缺少 platformMessageId")
    sender = _text_id(row.get("sender"))
    time_value = _at(row.get("timestamp"))
    content = row.get("content")
    if not sender or time_value is None or not isinstance(content, str) or not content.strip():
        return None
    reply_to = _text_id(row.get("replyToMessageId"))
    timestamp, at = time_value
    return ChatLabMessage(
        row_number,
        ordinal,
        sender,
        message_id,
        timestamp,
        at,
        content,
        reply_to,
        byte_offset,
        byte_length,
    )


def _jsonl_rows(path: Path) -> Iterator[tuple[int, dict | None, int, int]]:
    with path.open("rb") as stream:
        row_number = 0
        while True:
            offset = stream.tell()
            raw_line = stream.readline()
            if not raw_line:
                break
            row_number += 1
            try:
                line = raw_line.decode("utf-8-sig" if row_number == 1 else "utf-8")
            except UnicodeDecodeError:
                yield row_number, None, offset, len(raw_line)
                continue
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            try:
                row = json.loads(stripped)
            except json.JSONDecodeError:
                yield row_number, None, offset, len(raw_line)
                continue
            if not isinstance(row, dict):
                yield row_number, None, offset, len(raw_line)
                continue
            yield row_number, row, offset, len(raw_line)


def _json_data(path: Path) -> dict:
    try:
        with path.open("r", encoding="utf-8-sig") as stream:
            data = json.load(stream)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ChatLabFormatError("JSON 文件无法解析") from exc
    if not isinstance(data, dict):
        raise ChatLabFormatError("ChatLab JSON 根节点必须是对象")
    return data


def inspect_chatlab(path: str | Path) -> ChatLabInspection:
    """Validate file-level structure and return privacy-safe preview metadata."""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix not in {".json", ".jsonl"}:
        raise ChatLabFormatError("文件扩展名必须是 .json 或 .jsonl")
    fmt = "jsonl" if suffix == ".jsonl" else "json"
    warnings: list[dict[str, int | str]] = []
    counts: Counter[str] = Counter()
    member_map: dict[str, ChatLabMember]
    rows = accepted = skipped = missing_ids = 0
    first_stamp: tuple[float, str] | None = None
    last_stamp: tuple[float, str] | None = None

    if fmt == "json":
        data = _json_data(source)
        version, platform, kind, name = _header(data.get("chatlab"), data.get("meta"))
        member_map = _members(data.get("members"))
        messages = data.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ChatLabFormatError("ChatLab JSON messages 必须是非空数组")
        for ordinal, row in enumerate(messages):
            row_number = ordinal + 1
            if isinstance(row, dict) and not _text_id(row.get("platformMessageId")):
                missing_ids += 1
                continue
            try:
                parsed = _message(row, row_number, ordinal)
            except ChatLabIdentityError:
                missing_ids += 1
                continue
            rows += 1
            sender = _text_id(row.get("sender")) if isinstance(row, dict) else ""
            # Keep identifiable senders from invalid rows so a malformed body
            # cannot hide a third speaker from role validation.
            if sender:
                counts[sender] += 1
                member_map.setdefault(sender, ChatLabMember(sender, str(row.get("accountName") or "")))
            if parsed is None:
                skipped += 1
                if len(warnings) < MAX_PREVIEW_WARNINGS:
                    warnings.append({"row": row_number, "reason": "invalid_message"})
                continue
            accepted += 1
            stamp = (parsed.timestamp, parsed.at)
            first_stamp = stamp if first_stamp is None else min(first_stamp, stamp)
            last_stamp = stamp if last_stamp is None else max(last_stamp, stamp)
    else:
        iterator = _jsonl_rows(source)
        try:
            header_row = next(iterator)
        except StopIteration as exc:
            raise ChatLabFormatError("JSONL 缺少 header") from exc
        first_number, header, _, _ = header_row
        if first_number != 1 or header is None:
            raise ChatLabFormatError("JSONL 第一行必须是 header")
        if header.get("_type") != "header":
            raise ChatLabFormatError("JSONL 第一行必须是 header")
        version, platform, kind, name = _header(header.get("chatlab"), header.get("meta"))
        member_map = {}
        saw_message = False
        for row_number, row, _, _ in iterator:
            if row is None:
                skipped += 1
                if len(warnings) < MAX_PREVIEW_WARNINGS:
                    warnings.append({"row": row_number, "reason": "invalid_json"})
                continue
            row_type = row.get("_type")
            if row_type == "member":
                if saw_message:
                    raise ChatLabFormatError("JSONL member 行必须位于 message 行之前")
                member = _members([row])
                platform_id, value = next(iter(member.items()))
                old = member_map.get(platform_id)
                if old is not None and old != value:
                    raise ChatLabFormatError("JSONL 成员 platformId 冲突")
                member_map[platform_id] = value
                continue
            if row_type != "message":
                skipped += 1
                if len(warnings) < MAX_PREVIEW_WARNINGS:
                    warnings.append({"row": row_number, "reason": "unknown_row_type"})
                continue
            saw_message = True
            ordinal = rows + skipped + missing_ids
            if not _text_id(row.get("platformMessageId")):
                missing_ids += 1
                continue
            parsed = _message(row, row_number, ordinal)
            rows += 1
            sender = _text_id(row.get("sender"))
            # Keep identifiable senders from invalid rows so a malformed body
            # cannot hide a third speaker from role validation.
            if sender:
                counts[sender] += 1
                member_map.setdefault(sender, ChatLabMember(sender, str(row.get("accountName") or "")))
            if parsed is None:
                skipped += 1
                if len(warnings) < MAX_PREVIEW_WARNINGS:
                    warnings.append({"row": row_number, "reason": "invalid_message"})
                continue
            accepted += 1
            stamp = (parsed.timestamp, parsed.at)
            first_stamp = stamp if first_stamp is None else min(first_stamp, stamp)
            last_stamp = stamp if last_stamp is None else max(last_stamp, stamp)
        if not saw_message:
            raise ChatLabFormatError("JSONL 至少需要一条 message 行")

    if rows == 0 or accepted == 0:
        raise ChatLabFormatError("文件没有可接纳的消息")
    return ChatLabInspection(
        fmt,
        version,
        platform,
        kind,
        name,
        tuple(member_map[key] for key in sorted(member_map)),
        dict(counts),
        rows,
        accepted,
        skipped,
        missing_ids,
        first_stamp[1] if first_stamp else "",
        last_stamp[1] if last_stamp else "",
        tuple(warnings),
    )


def iter_chatlab_messages(path: str | Path) -> Iterator[ChatLabMessage]:
    """Yield valid text messages without retaining a JSONL file in memory."""
    source = Path(path)
    if source.suffix.lower() == ".jsonl":
        ordinal = 0
        for row_number, row, byte_offset, byte_length in _jsonl_rows(source):
            if row is None:
                continue
            if row.get("_type") != "message":
                continue
            parsed = _message(row, row_number, ordinal, byte_offset, byte_length)
            ordinal += 1
            if parsed is not None:
                yield parsed
        return
    data = _json_data(source)
    messages = data.get("messages")
    if not isinstance(messages, list):
        raise ChatLabFormatError("ChatLab JSON messages 必须是数组")
    for ordinal, row in enumerate(messages):
        parsed = _message(row, ordinal + 1, ordinal)
        if parsed is not None:
            yield parsed


def iter_chatlab_messages_sorted(path: str | Path) -> Iterator[ChatLabMessage]:
    """Yield messages by event time with bounded-memory JSONL external sorting."""
    source = Path(path)
    if source.suffix.lower() == ".json":
        yield from sorted(
            iter_chatlab_messages(source),
            key=lambda row: (row.timestamp, row.ordinal),
        )
        return
    if source.suffix.lower() != ".jsonl":
        raise ChatLabFormatError("文件扩展名必须是 .json 或 .jsonl")

    with tempfile.TemporaryDirectory(prefix="seekmemory-chatlab-sort-") as temp:
        root = Path(temp)
        run_paths: list[Path] = []
        chunk: list[tuple[float, int, int, int, int]] = []
        ordinal = 0
        saw_header = False
        saw_message = False
        for row_number, row, offset, length in _jsonl_rows(source):
            if row is None:
                continue
            row_type = row.get("_type")
            if not saw_header:
                if row_number != 1 or row_type != "header":
                    raise ChatLabFormatError("JSONL 第一行必须是 header")
                _header(row.get("chatlab"), row.get("meta"))
                saw_header = True
                continue
            if row_type != "message":
                continue
            saw_message = True
            parsed = _message(row, row_number, ordinal, offset, length)
            ordinal += 1
            if parsed is None:
                continue
            chunk.append((parsed.timestamp, parsed.ordinal, offset, length, row_number))
            if len(chunk) >= SORT_RUN_RECORDS:
                run_paths.append(_write_sort_run(root, len(run_paths), chunk))
                chunk = []
        if not saw_header:
            raise ChatLabFormatError("JSONL 缺少 header")
        if not saw_message:
            raise ChatLabFormatError("JSONL 至少需要一条 message 行")
        if chunk:
            run_paths.append(_write_sort_run(root, len(run_paths), chunk))
        if not run_paths:
            return
        yield from _merge_sort_runs(source, run_paths)


def _write_sort_run(
    root: Path, run_number: int, rows: list[tuple[float, int, int, int, int]]
) -> Path:
    rows.sort(key=lambda row: (row[0], row[1]))
    path = root / f"run-{run_number:05d}.bin"
    with path.open("wb") as stream:
        for timestamp, ordinal, offset, length, row_number in rows:
            stream.write(_SORT_RECORD.pack(timestamp, ordinal, offset, length, row_number))
    return path


def _merge_sort_runs(source: Path, run_paths: list[Path]) -> Iterator[ChatLabMessage]:
    runs = [path.open("rb") for path in run_paths]
    input_stream = source.open("rb")
    heap: list[tuple[float, int, int, int, int, int]] = []

    def take(run_index: int) -> None:
        raw = runs[run_index].read(_SORT_RECORD.size)
        if len(raw) != _SORT_RECORD.size:
            return
        timestamp, ordinal, offset, length, row_number = _SORT_RECORD.unpack(raw)
        heapq.heappush(
            heap, (timestamp, ordinal, offset, length, row_number, run_index)
        )

    try:
        for index in range(len(runs)):
            take(index)
        while heap:
            _, ordinal, offset, length, row_number, run_index = heapq.heappop(heap)
            input_stream.seek(offset)
            try:
                row = json.loads(input_stream.read(length).decode("utf-8-sig" if offset == 0 else "utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ChatLabFormatError("JSONL 在预览后发生变化") from exc
            parsed = _message(row, row_number, ordinal, offset, length)
            if parsed is not None:
                yield parsed
            take(run_index)
    finally:
        input_stream.close()
        for run in runs:
            run.close()


class ChatLabReader:
    """HistoryReader implementation for ChatLab v0.0.2 JSON and JSONL."""

    inspect = staticmethod(inspect_chatlab)
    iter_messages = staticmethod(iter_chatlab_messages)
    iter_messages_sorted = staticmethod(iter_chatlab_messages_sorted)
