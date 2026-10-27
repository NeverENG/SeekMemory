"""Pending dialogue buffer with lightweight topic segmentation and TTL signals."""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

try:
    from ..app.contracts import DialogueTurn, ExtractionState
    from ..app.topic_policy import (
        TOPIC_GAP_SECONDS,
        TOPIC_SIMILARITY,
        assign_topic,
        new_topic_id as _new_topic_id,
    )
    from ..core.source import Source, make_source_id
except ImportError:
    from app.contracts import DialogueTurn, ExtractionState
    from app.topic_policy import (
        TOPIC_GAP_SECONDS,
        TOPIC_SIMILARITY,
        assign_topic,
        new_topic_id as _new_topic_id,
    )
    from core.source import Source, make_source_id

TOPIC_TTL_SECONDS = 86400


def _parse_at(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None


class Buffer:
    """In-memory view of a Source-backed extraction projection.

    A path-only Buffer keeps the legacy JSON test/support behavior. When a repository is
    supplied, queued turns are rebuilt from Source plus extraction_state.
    """

    def __init__(self, path: str = "", extraction=None) -> None:
        self.path = str(path or "")
        self._extraction = extraction
        self.items: list[DialogueTurn] = []
        self.last_ts = 0.0
        self.load_error = ""
        self.save_error = ""
        self.load()

    def _last_for_session(self, session_id: str) -> DialogueTurn | None:
        for turn in reversed(self.items):
            if turn.session_id == session_id:
                return turn
        return None

    def _paired_parent(self, turn: DialogueTurn) -> DialogueTurn | None:
        """Find the user turn this one replies to; the session must match.

        ``reply_to`` points at the parent Source id, so only an actual user
        Source can be a parent. The scan covers the whole pending queue instead
        of a fixed recent window, because an old parent may still be queued.
        """
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
        """Rebuild the in-memory queue from Source after admission release."""
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
        """Give a repository-backed turn its immutable Source and extraction state.

        Host callers may add a turn without a Source id. The pending projection
        deduplicates by Source id, so an empty id would collapse every such turn
        into one row; synthesize the id and let ``enqueue_extraction`` write the
        Source and its extraction state together.
        """
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
        """Keep one row per non-empty Source id; source-less rows stay distinct."""
        seen: set[str] = set()
        kept: list[DialogueTurn] = []
        for item in items:
            if item.source_id and item.source_id in seen:
                continue
            seen.add(item.source_id)
            kept.append(item)
        return kept

    def _topic_for(self, turn: DialogueTurn, previous: DialogueTurn | None,
                   parent: DialogueTurn | None = None) -> str:
        return assign_topic(turn, previous, parent).topic_id

    def topics(self) -> list[tuple[str, str, list[DialogueTurn]]]:
        groups: dict[tuple[str, str], list[DialogueTurn]] = {}
        for turn in self.items:
            groups.setdefault((turn.session_id, turn.topic_id), []).append(turn)
        return [(session, topic, rows) for (session, topic), rows in groups.items()]

    def idle_seconds(self) -> float:
        return max(0.0, time.time() - self.last_ts)

    def oldest_topic_age(self) -> float:
        stamps = [_parse_at(turn.at) for turn in self.items]
        valid = [stamp for stamp in stamps if stamp is not None]
        if not valid:
            return 0.0
        return max(0.0, (datetime.now() - min(valid)).total_seconds())

    def should_flush(self, idle_seconds: float, min_items: int) -> bool:
        if not self.items:
            return False
        return len(self.items) >= max(1, min_items) and self.idle_seconds() >= idle_seconds

    def take(self) -> list[DialogueTurn]:
        items = self.items
        self.items = []
        self.save()
        return items

    def take_topics(self, topic_ids: set[str]) -> list[DialogueTurn]:
        wanted = {str(x) for x in topic_ids}
        taken = [turn for turn in self.items if turn.topic_id in wanted]
        self.items = [turn for turn in self.items if turn.topic_id not in wanted]
        self.save()
        return taken

    def restore(self, rows: list[DialogueTurn]) -> None:
        if not rows:
            return
        existing = set(self.items)
        restored = [row for row in rows if row not in existing]
        self.items = restored + self.items
        self.save()

    def save(self) -> bool:
        if not self.path or (self._extraction is not None and all(t.source_id for t in self.items)):
            self.save_error = ""
            return True
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"last": self.last_ts, "items": [asdict(t) for t in self.items]},
                          f, ensure_ascii=False)
            self.save_error = ""
            return True
        except Exception as exc:
            self.save_error = type(exc).__name__
            return False

    def load(self) -> None:
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
        if not self.path or not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            self.load_error = type(exc).__name__
            self._quarantine()
            return {}
        if not isinstance(data, dict):
            self.load_error = "InvalidPendingFile"
            self._quarantine()
            return {}
        self.load_error = ""
        return data

    def _quarantine(self) -> None:
        """Preserve a corrupt pending file instead of overwriting it on save."""
        if not self.path or not os.path.exists(self.path):
            return
        target = Path(self.path + ".corrupt")
        suffix = 1
        while target.exists():
            target = Path(f"{self.path}.corrupt.{suffix}")
            suffix += 1
        try:
            Path(self.path).replace(target)
        except OSError:
            pass

    def mark_succeeded(self, rows: list[DialogueTurn]) -> int:
        """Mark rows extracted and refresh the projection without deleting Source."""
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
        """Retain failed rows and record only a bounded exception type."""
        source_ids = [turn.source_id for turn in rows if turn.source_id]
        if self._extraction is None:
            return 0
        return self._extraction.mark_extraction_failed(
            source_ids, error_type, max_attempts=max_attempts
        )

    def migrate_legacy(self) -> int:
        """Move pending.json into Source + extraction_state without content loss."""
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
        if isinstance(row, dict):
            try:
                turn = DialogueTurn(
                    str(row.get("session_id") or ""),
                    str(row.get("speaker_id") or ""),
                    str(row.get("role") or "user"),
                    str(row.get("text") or ""),
                    str(row.get("at") or ""),
                    str(row.get("source_id") or ""),
                    str(row.get("topic_id") or ""),
                    str(row.get("turn_id") or ""),
                    str(row.get("reply_to") or "") or None,
                )
            except Exception:
                return None
        elif isinstance(row, (list, tuple)):
            if len(row) >= 5:
                turn = DialogueTurn(str(row[0]), str(row[1]), str(row[2]), str(row[3]),
                                    "", str(row[4]), "")
            elif len(row) == 4:
                turn = DialogueTurn(str(row[0]), str(row[1]), str(row[2]), str(row[3]))
            elif len(row) == 3:
                turn = DialogueTurn(str(row[0]), "", str(row[1]), str(row[2]))
            else:
                return None
        else:
            return None
        if not turn.text.strip():
            return None
        if turn.topic_id:
            return turn
        return replace(turn, topic_id=_new_topic_id(turn))
