"""Host-neutral queries over the existing allowlisted runtime trace snapshot."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime

from ..core.trace import FILTERS

RUN_STATUSES = {"all", "running", "completed", "error", "interrupted"}


def _timestamp(value: str) -> float | None:
    if not value:
        return None
    # Python 3.10 does not accept a trailing Z in fromisoformat.
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("invalid_trace_timestamp") from None
    if parsed.tzinfo is None:
        raise ValueError("trace_query_requires_timezone")
    return parsed.timestamp()


@dataclass(frozen=True)
class TraceQuery:
    state: str = "all"
    status: str = "all"
    run_id: str = ""
    since: float | None = None
    until: float | None = None

    @classmethod
    def parse(cls, query: Mapping[str, str]) -> TraceQuery:
        """Validate filters before reading traces; errors never echo input."""
        state, status = query.get("state", "all"), query.get("status", "all")
        run_id = query.get("run_id", "")
        if state not in FILTERS or status not in RUN_STATUSES:
            raise ValueError("invalid_trace_filter")
        if run_id and not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("invalid_trace_run_id")
        since, until = _timestamp(query.get("since", "")), _timestamp(query.get("until", ""))
        if since is not None and until is not None and since > until:
            raise ValueError("invalid_trace_time_range")
        return cls(state, status, run_id, since, until)

    def matches(self, run: dict) -> bool:
        """Match by last event time and retain the complete available timeline."""
        updated = _timestamp(run["updated_at"])
        return ((not self.run_id or run["id"] == self.run_id)
                and (self.status == "all" or run["status"] == self.status)
                and (self.since is None or updated >= self.since)
                and (self.until is None or updated <= self.until))


def query_traces(snapshot: Callable[[str], dict], values: Mapping[str, str]) -> dict:
    """Query the shared bounded snapshot without host objects or database reads."""
    query = TraceQuery.parse(values)
    result = snapshot(query.state)
    runs = [run for run in result["runs"] if query.matches(run)]
    visible = {run["id"] for run in runs}
    return {**result, "runs": runs,
            "events": [event for event in result["events"] if event["run_id"] in visible]}
