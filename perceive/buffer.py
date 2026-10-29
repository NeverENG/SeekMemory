"""Own pending queue projections and coordinate topic rules and legacy files; repositories and files retain separate ownership.

管理待处理队列视图并协调话题规则与旧文件，仓储和文件各自拥有明确职责。
"""

from __future__ import annotations

import os
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

try:
    from ..app.contracts import DialogueTurn, ExtractionState
    from ..core.source import Source, make_source_id
except ImportError:
    from app.contracts import DialogueTurn, ExtractionState
    from core.source import Source, make_source_id

from .buffer_policy import (
    TOPIC_GAP_SECONDS, TOPIC_SIMILARITY, TOPIC_TTL_SECONDS,
    _parse_at, _bigrams, _dice, _new_topic_id, topic_for,
)
from .buffer_codec import turn_from_row, unique_by_source
from .pending_file import PendingFile
from .ports import ExtractionStore


class Buffer:
    """Own a pending Source projection; use legacy JSON only for compatibility input / 管理待处理原始消息视图，旧 JSON 仅用于兼容输入。"""

    def __init__(self, path: str = "", extraction: ExtractionStore | None = None) -> None:
        self._legacy = PendingFile(path)
        self._extraction = extraction
        self.items: list[DialogueTurn] = []
        self.last_ts = 0.0
        self.load()

    @property
    def path(self) -> str:
        """Read the legacy file path / 读取旧文件的 path。"""
        return self._legacy.path

    @path.setter
    def path(self, value: str) -> None:
        """Update the legacy file path / 更新旧文件的 path。"""
        self._legacy.path = str(value or "")

    @property
    def load_error(self) -> str:
        """Read the legacy file load_error / 读取旧文件的 load_error。"""
        return self._legacy.load_error

    @load_error.setter
    def load_error(self, value: str) -> None:
        """Update the legacy file load_error / 更新旧文件的 load_error。"""
        self._legacy.load_error = str(value or "")

    @property
    def save_error(self) -> str:
        """Read the legacy file save_error / 读取旧文件的 save_error。"""
        return self._legacy.save_error

    @save_error.setter
    def save_error(self, value: str) -> None:
        """Update the legacy file save_error / 更新旧文件的 save_error。"""
        self._legacy.save_error = str(value or "")

    def _last_for_session(self, session_id: str) -> DialogueTurn | None:
        """Read the latest pending row in one session / 读取一个会话中最新的待处理行。"""
        for turn in reversed(self.items):
            if turn.session_id == session_id:
                return turn
        return None

    def _paired_parent(self, turn: DialogueTurn) -> DialogueTurn | None:
        """Read the exact same-session pending user parent referenced by reply_to / 读取 reply_to 引用的同会话精确待处理用户父消息。"""
        reply_to = str(turn.reply_to or "")
        if not reply_to:
            return None
        for candidate in reversed(self.items):
            if candidate.session_id != turn.session_id:
                continue
            if candidate.role == "user" and candidate.source_id == reply_to:
                return candidate
        return None

    def add(
        self,
        umo: str,
        text: str,
        sender: str = "",
        source_id: str = "",
        at: str = "",
        *,
        source: Source | None = None,
        turn_id: str = "",
        reply_to: str = "",
        deferred: bool = False,
        role: str = "user",
    ) -> DialogueTurn | None:
        """Admit Source-backed input before publishing its pending view; ignore empty text / 先接纳具有原始消息的输入，再发布待处理视图，忽略空文本。"""
        text = str(text or "").strip()
        if not text:
            return None
        if source is not None:
            source_id = source_id or source.id
            turn_id = turn_id or source.turn_id
            reply_to = reply_to or str(source.reply_to or "")
        turn = DialogueTurn(
            str(umo or ""), str(sender or ""), str(role or "user"), text,
            str(at or ""), str(source_id or ""), "",
            str(turn_id or ""), str(reply_to or "") or None,
        )
        previous = self._last_for_session(turn.session_id)
        parent = self._paired_parent(turn)
        turn = replace(turn, topic_id=self._topic_for(turn, previous, parent))
        if self._extraction is not None:
            turn = self._enqueue(turn, source=source, turn_id=turn_id, deferred=deferred)
        if not deferred:
            self.items.append(turn)
            if self._extraction is not None:
                self.items = self._unique_by_source(self.items)
        self.last_ts = time.time()
        self.save()
        return turn

    def reload(self) -> int:
        """Rebuild the pending projection after deferred admission is released / 在延后接纳释放后重建待处理视图。"""
        if self._extraction is None:
            return len(self.items)
        self._load_projection()
        return len(self.items)

    def _enqueue(
        self,
        turn: DialogueTurn,
        *,
        source: Source | None,
        turn_id: str,
        deferred: bool = False,
    ) -> DialogueTurn:
        """Assign missing Source identity and atomically admit Source plus queue state / 补充缺失原始消息身份并原子接纳原始消息及队列状态。"""
        at = turn.at or datetime.now().isoformat(timespec="seconds")
        source_id = turn.source_id or make_source_id(
            session_id=turn.session_id,
            speaker_id=turn.speaker_id,
            role=turn.role,
            text=turn.text,
            at=at,
        )
        if source_id != turn.source_id or at != turn.at:
            turn = replace(turn, source_id=source_id, at=at)
        queued = source or Source(
            source_id,
            str(turn.turn_id or turn_id or source_id),
            turn.session_id,
            turn.speaker_id,
            turn.role,
            turn.text,
            at,
            turn.reply_to,
        )
        self._extraction.enqueue_extraction(queued, turn.topic_id, at, deferred=deferred)
        return replace(turn, turn_id=queued.turn_id, reply_to=queued.reply_to)

    @staticmethod
    def _unique_by_source(items: list[DialogueTurn]) -> list[DialogueTurn]:
        """Keep one row per nonempty Source ID, retaining distinct source-less rows / 每个非空原始消息编号仅保留一行，无编号行仍分别保留。"""
        return unique_by_source(items)

    def _topic_for(self, turn: DialogueTurn, previous: DialogueTurn | None,
                   parent: DialogueTurn | None = None) -> str:
        """Delegate the existing same-session topic rule / 委托执行既有同会话话题规则。"""
        return topic_for(turn, previous, parent)

    def topics(self) -> list[tuple[str, str, list[DialogueTurn]]]:
        """Group pending rows by session and topic without consuming them / 按会话和话题分组待处理行，不消费这些行。"""
        groups: dict[tuple[str, str], list[DialogueTurn]] = {}
        for turn in self.items:
            groups.setdefault((turn.session_id, turn.topic_id), []).append(turn)
        return [(session, topic, rows) for (session, topic), rows in groups.items()]

    def idle_seconds(self) -> float:
        """Read elapsed time since the latest admitted turn / 读取距最新接纳消息的经过时长。"""
        return max(0.0, time.time() - self.last_ts)

    def oldest_topic_age(self) -> float:
        """Read the oldest valid pending timestamp using existing local-time semantics / 沿用现有本地时间语义读取最旧有效待处理时间的时长。"""
        stamps = [_parse_at(turn.at) for turn in self.items]
        valid = [stamp for stamp in stamps if stamp is not None]
        if not valid:
            return 0.0
        return max(0.0, (datetime.now() - min(valid)).total_seconds())

    def should_flush(self, idle_seconds: float, min_items: int) -> bool:
        """Check the legacy minimum-count and idle-duration gates / 检查旧的最少数量及空闲时长条件。"""
        if not self.items:
            return False
        return len(self.items) >= max(1, min_items) and self.idle_seconds() >= idle_seconds

    def take(self) -> list[DialogueTurn]:
        """Consume and save the legacy pending view, returning its previous rows / 消费并保存旧待处理视图，返回原有行。"""
        items = self.items
        self.items = []
        self.save()
        return items

    def take_topics(self, topic_ids: set[str]) -> list[DialogueTurn]:
        """Consume selected legacy topics and save the remaining view / 消费选定的旧话题并保存剩余视图。"""
        wanted = {str(x) for x in topic_ids}
        taken = [turn for turn in self.items if turn.topic_id in wanted]
        self.items = [turn for turn in self.items if turn.topic_id not in wanted]
        self.save()
        return taken

    def restore(self, rows: list[DialogueTurn]) -> None:
        """Restore distinct rows and save the pending view / 恢复不同的行并保存待处理视图。"""
        if not rows:
            return
        existing = set(self.items)
        restored = [row for row in rows if row not in existing]
        self.items = restored + self.items
        self.save()

    def save(self) -> bool:
        """Persist legacy-only input; Source-backed rows already live in the queue.

        保存仅由旧文件持有的输入，带原始消息编号的行已保存在队列中。
        """
        if not self.path or (self._extraction is not None and all(t.source_id for t in self.items)):
            self.save_error = ""
            return True
        try:
            data = {"last": self.last_ts, "items": [asdict(turn) for turn in self.items]}
        except Exception as exc:
            self.save_error = type(exc).__name__
            return False
        return self._legacy.save(data)

    def load(self) -> None:
        """Read Source-backed projection or legacy pending input / 读取原始消息支持的视图或旧待处理输入。"""
        if self._extraction is not None:
            self._load_projection()
            return
        if not self.path:
            return
        data = self._read_file()
        kept: list[DialogueTurn] = []
        for row in data.get("items") or []:
            turn = self._from_row(row)
            if turn is not None:
                kept.append(turn)
        self.items = kept
        try:
            self.last_ts = float(data.get("last") or 0.0)
        except (TypeError, ValueError):
            self.last_ts = 0.0

    def _load_projection(self) -> None:
        """Read pending Source rows into the in-memory projection / 将待处理原始消息行读入内存视图。"""
        self.items = []
        for row in self._extraction.pending_extractions():
            self.items.append(
                DialogueTurn(
                    str(row["session_id"]),
                    str(row["speaker_id"]),
                    str(row["role"]),
                    str(row["text"]),
                    str(row["at"]),
                    str(row["source_id"]),
                    str(row["topic_id"]),
                    str(row.get("turn_id") or ""),
                    str(row.get("reply_to") or "") or None,
                )
            )
        stamps = [_parse_at(turn.at) for turn in self.items]
        valid = [stamp.timestamp() for stamp in stamps if stamp is not None]
        self.last_ts = max(valid, default=0.0)

    def _read_file(self) -> dict:
        """Read legacy input through its single file owner / 通过唯一文件所有者读取旧输入。"""
        return self._legacy.read()

    def _quarantine(self) -> None:
        """Preserve corrupt legacy input through its file owner / 通过文件所有者保留损坏的旧输入。"""
        self._legacy.quarantine()

    def mark_succeeded(self, rows: list[DialogueTurn]) -> int:
        """Confirm supplied queue rows without deleting Source evidence / 确认给定队列行，不删除原始证据。"""
        source_ids = [turn.source_id for turn in rows if turn.source_id]
        changed = (
            self._extraction.mark_extraction_succeeded(source_ids)
            if self._extraction is not None
            else 0
        )
        wanted = set(source_ids)
        self.items = [item for item in self.items if item.source_id not in wanted]
        self.save()
        return changed

    def mark_failed(
        self, rows: list[DialogueTurn], error_type: str, *, max_attempts: int = 5
    ) -> int:
        """Retain unfinished input with bounded retry metadata / 保留未完成输入及有上限的重试信息。"""
        source_ids = [turn.source_id for turn in rows if turn.source_id]
        if self._extraction is None:
            return 0
        return self._extraction.mark_extraction_failed(
            source_ids, error_type, max_attempts=max_attempts
        )

    def migrate_legacy(self) -> int:
        """Admit supported legacy rows before archiving the original file; retain Source / 在归档原文件前接纳受支持的旧行，并保留原始消息。"""
        if self._extraction is None or not self.path or not os.path.exists(self.path):
            return 0
        data = self._read_file()
        migrated = 0
        rows = data.get("items") or []
        for row in rows:
            turn = self._from_row(row)
            if turn is None:
                continue
            source_id = turn.source_id or make_source_id(
                session_id=turn.session_id,
                speaker_id=turn.speaker_id,
                role=turn.role,
                text=turn.text,
                at=turn.at,
            )
            source = Source(
                source_id,
                turn.turn_id or source_id,
                turn.session_id,
                turn.speaker_id,
                turn.role,
                turn.text,
                turn.at,
                turn.reply_to,
            )
            self._extraction.enqueue_extraction(source, turn.topic_id, turn.at)
            migrated += 1
        if migrated and migrated == len(rows):
            target = Path(self.path + ".migrated")
            suffix = 1
            while target.exists():
                target = Path(f"{self.path}.migrated.{suffix}")
                suffix += 1
            Path(self.path).replace(target)
        self._load_projection()
        return migrated

    @staticmethod
    def _from_row(row) -> DialogueTurn | None:
        """Decode a supported legacy row without I/O / 转换受支持的旧行，不执行读写。"""
        return turn_from_row(row)
