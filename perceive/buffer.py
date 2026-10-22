"""Pending dialogue buffer with lightweight topic segmentation and TTL signals."""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path

try:
    from ..app.contracts import DialogueTurn, ExtractionState
    from ..core.source import Source, make_source_id
    from ..store.db import DB
except ImportError:
    from app.contracts import DialogueTurn, ExtractionState
    from core.source import Source, make_source_id
    from store.db import DB

LEGACY_KEEP = 200
TOPIC_GAP_SECONDS = 5400
TOPIC_SIMILARITY = 0.12
TOPIC_TTL_SECONDS = 86400


def _parse_at(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None


def _bigrams(text: str) -> set[str]:
    clean = "".join(ch.lower() for ch in str(text or "") if ch.isalnum())
    return {clean[i:i + 2] for i in range(max(0, len(clean) - 1))}


def _dice(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def _new_topic_id(turn: DialogueTurn) -> str:
    raw = f"{turn.session_id}|{turn.at}|{turn.text}"
    return "tp_" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


class Buffer:
    """In-memory view of a Source-backed extraction projection.

    A path-only Buffer keeps the legacy JSON test/support behavior. When a DB is
    supplied, queued turns are rebuilt from Source plus extraction_state.
    """

    def __init__(self, path: str = "", db: DB | None = None) -> None:
        self.path = str(path or "")
        self._db = db
        self.items: list[DialogueTurn] = []
        self.last_ts = 0.0
        self.load()

    def _last_for_session(self, session_id: str) -> DialogueTurn | None:
        for turn in reversed(self.items):
            if turn.session_id == session_id:
                return turn
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
        deferred: bool = False,
    ) -> DialogueTurn | None:
        text = str(text or "").strip()
        if not text:
            return None
        turn = DialogueTurn(str(umo or ""), str(sender or ""), "user", text,
                            str(at or ""), str(source_id or ""))
        previous = self._last_for_session(turn.session_id)
        turn = DialogueTurn(turn.session_id, turn.speaker_id, turn.role, turn.text,
                            turn.at, turn.source_id, self._topic_for(turn, previous))
        if self._db is not None:
            turn = self._enqueue(turn, source=source, turn_id=turn_id, deferred=deferred)
        if not deferred:
            self.items.append(turn)
            if self._db is None:
                self.items = self.items[-LEGACY_KEEP:]
            else:
                self.items = self._unique_by_source(self.items)
        self.last_ts = time.time()
        self.save()
        return turn

    def reload(self) -> int:
        """Rebuild the in-memory queue from Source after admission release."""
        if self._db is None:
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
        """Give a DB-backed turn its immutable Source and extraction state.

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
            str(turn_id or source_id),
            turn.session_id,
            turn.speaker_id,
            turn.role,
            turn.text,
            at,
        )
        self._db.enqueue_extraction(queued, turn.topic_id, at, deferred=deferred)
        return turn

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

    def _topic_for(self, turn: DialogueTurn, previous: DialogueTurn | None) -> str:
        if previous is None or not previous.topic_id:
            return _new_topic_id(turn)
        current_at, previous_at = _parse_at(turn.at), _parse_at(previous.at)
        if current_at is not None and previous_at is not None:
            if (current_at - previous_at).total_seconds() > TOPIC_GAP_SECONDS:
                return _new_topic_id(turn)
        if _dice(_bigrams(turn.text), _bigrams(previous.text)) < TOPIC_SIMILARITY:
            return _new_topic_id(turn)
        return previous.topic_id

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
        if self._db is None:
            self.items = self.items[-LEGACY_KEEP:]
        self.save()

    def save(self) -> None:
        if not self.path or (self._db is not None and all(t.source_id for t in self.items)):
            return
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({"last": self.last_ts, "items": [asdict(t) for t in self.items]},
                          f, ensure_ascii=False)
        except Exception:
            pass

    def load(self) -> None:
        if self._db is not None:
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
        self.items = kept[-LEGACY_KEEP:]
        try:
            self.last_ts = float(data.get("last") or 0.0)
        except (TypeError, ValueError):
            self.last_ts = 0.0

    def _load_projection(self) -> None:
        self.items = []
        for row in self._db.pending_extractions():
            self.items.append(
                DialogueTurn(
                    str(row["session_id"]),
                    str(row["speaker_id"]),
                    str(row["role"]),
                    str(row["text"]),
                    str(row["at"]),
                    str(row["source_id"]),
                    str(row["topic_id"]),
                )
            )
        stamps = [_parse_at(turn.at) for turn in self.items]
        valid = [stamp.timestamp() for stamp in stamps if stamp is not None]
        self.last_ts = max(valid, default=0.0)

    def _read_file(self) -> dict:
        if not self.path:
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def mark_succeeded(self, rows: list[DialogueTurn]) -> int:
        """Mark rows extracted and refresh the projection without deleting Source."""
        source_ids = [turn.source_id for turn in rows if turn.source_id]
        changed = (
            self._db.mark_extraction_succeeded(source_ids)
            if self._db is not None
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
        if self._db is None:
            return 0
        return self._db.mark_extraction_failed(
            source_ids, error_type, max_attempts=max_attempts
        )

    def migrate_legacy(self) -> int:
        """Move pending.json into Source + extraction_state without content loss."""
        if self._db is None or not self.path or not os.path.exists(self.path):
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
                source_id,
                turn.session_id,
                turn.speaker_id,
                turn.role,
                turn.text,
                turn.at,
            )
            self._db.enqueue_extraction(source, turn.topic_id, turn.at)
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
                turn = DialogueTurn(str(row.get("session_id") or ""),
                                    str(row.get("speaker_id") or ""),
                                    str(row.get("role") or "user"),
                                    str(row.get("text") or ""),
                                    str(row.get("at") or ""),
                                    str(row.get("source_id") or ""),
                                    str(row.get("topic_id") or ""))
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
        return turn if turn.topic_id else DialogueTurn(
            turn.session_id, turn.speaker_id, turn.role, turn.text,
            turn.at, turn.source_id, _new_topic_id(turn))
