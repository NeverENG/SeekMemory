"""Bounded operational trace, kept separate from business journal events.

The Trace ring is the scheduler's own sample of capacity transitions and
maintenance actions.  It never stores message text, only counts and state names,
so a future AgentHook trace can reuse this shape without sharing the Journal
deque or its on-disk event log.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

TRACE_MAXLEN = 500
TRACE_TARGET = 400
_MAX_CONTEXT_ITEMS = 16


@dataclass(frozen=True)
class TraceRow:
    """One bounded operational sample."""

    at: str
    kind: str
    status: str
    context: dict[str, Any] = field(default_factory=dict)


class Trace:
    """In-memory ring of operational samples with an explicit trim target."""

    def __init__(self, maxlen: int = TRACE_MAXLEN) -> None:
        self.rows: deque[TraceRow] = deque(maxlen=max(1, int(maxlen)))

    def record(
        self, kind: str, status: str, context: dict[str, Any] | None = None
    ) -> None:
        """Append one sample; only scalar counts and names are kept."""
        safe: dict[str, Any] = {}
        for key, value in list((context or {}).items())[:_MAX_CONTEXT_ITEMS]:
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe[str(key)[:60]] = value
        self.rows.append(
            TraceRow(
                at=datetime.now(timezone.utc).isoformat(),
                kind=str(kind)[:60],
                status=str(status)[:40],
                context=safe,
            )
        )

    @property
    def count(self) -> int:
        return len(self.rows)

    def oldest_age_seconds(self, now: datetime | None = None) -> float:
        """Age of the oldest retained sample in seconds."""
        if not self.rows:
            return 0.0
        try:
            oldest = datetime.fromisoformat(self.rows[0].at)
        except (TypeError, ValueError):
            return 0.0
        current = now or datetime.now(timezone.utc)
        return max(0.0, current.timestamp() - oldest.timestamp())

    def trim(self, target: int = TRACE_TARGET) -> int:
        """Drop the oldest samples while keeping the newest ``target`` rows."""
        keep = max(0, min(int(target), self.rows.maxlen or TRACE_MAXLEN))
        removed = max(0, len(self.rows) - keep)
        for _ in range(removed):
            self.rows.popleft()
        return removed
