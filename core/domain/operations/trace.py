"""Sanitize content-free trace data and project runs without host or storage access.

清理无正文追踪数据并转换运行视图，不访问宿主或存储。
"""
from __future__ import annotations

import math
import re
from datetime import datetime, timezone

from ..memory.disclosure import DisclosureLevel

# Trace contract values and internal storage bounds stay with trace projection.
EVENTS = {"agent_begin", "llm_request", "llm_response", "agent_done",
          "message_sent", "tool_call", "tool_result"}
FILTERS = {"all", "not_recalled", "recalled_but_withheld",
           "recalled_and_injected", "fallback_used"}
STATUSES = {"running", "ok", "error", "unknown"}
_ID = re.compile(r"[A-Za-z0-9_-]{1,96}\Z")
ID_LIMIT = 256
_COUNT_LIMIT = 1_000_000_000
_DISCLOSURE_LEVELS = tuple(level.value for level in DisclosureLevel)
_RECALL_MODES = {"none", "strict", "loose"}
_FALLBACKS = {"", "recent_profile", "recent_topic"}


def ids(values) -> list[str]:
    """Keep bounded valid generated identities and remove duplicates.

    保留有界合法生成编号并去重。
    """
    if not isinstance(values, (list, tuple)):
        return []
    return list(dict.fromkeys(v for v in values if isinstance(v, str) and _ID.fullmatch(v)))[:ID_LIMIT]


def count(value) -> int:
    """Normalize a bounded nonnegative diagnostic count.

    整理有界非负诊断计数。
    """
    return max(0, min(value, _COUNT_LIMIT)) if type(value) is int else 0


def choice(value, allowed, default):
    """Keep an allowed string or use the supplied default.

    保留允许的字符串，否则使用给定默认值。
    """
    return value if isinstance(value, str) and value in allowed else default


def recall_data(info: dict) -> dict:
    """Whitelist generated identities, bounded counts and fixed enum values.

    仅保留白名单生成编号、有界计数及固定枚举值。
    """
    disclosure = info.get("disclosure", {})
    disclosure = disclosure if isinstance(disclosure, dict) else {}
    levels = {k: v for k, v in disclosure.items()
              if isinstance(k, str) and _ID.fullmatch(k)
              and v in _DISCLOSURE_LEVELS}
    gate = info.get("gate", {})
    gate = gate if isinstance(gate, dict) else {}
    threshold = gate.get("threshold", 0)
    if type(threshold) not in (int, float) or not math.isfinite(threshold):
        threshold = 0
    return {
        "mode": choice(info.get("mode"), _RECALL_MODES, "none"),
        "candidates": count(info.get("candidates")),
        "picked_ids": ids(info.get("picked_ids")),
        "pinned_ids": ids(info.get("pinned_ids")),
        "artifact_ids": ids(info.get("final_ids", info.get("artifact_ids"))),
        "dropped_ids": ids(info.get("dropped_ids")),
        "withheld_ids": ids([k for k, v in levels.items() if v == "silence"]),
        "disclosure": dict(list(levels.items())[:ID_LIMIT]),
        "fallback": choice(info.get("fallback"), _FALLBACKS, ""),
        "chars": count(info.get("chars")),
        "gate": {"evaluated": gate.get("evaluated") is True,
                 "passed": count(gate.get("passed")), "rejected": count(gate.get("rejected")),
                 "threshold": max(0.0, float(threshold))},
    }


def clean_event(row: dict) -> dict:
    """Validate identity/time and sanitize known fields on write and reload; discard unknown fields.

    在写入及重载时校验编号和时间并清理已知字段，丢弃未知字段。
    """
    if row.get("event") not in EVENTS or not re.fullmatch(r"[a-f0-9]{32}", str(row.get("run_id", ""))):
        raise ValueError("invalid_trace_event")
    at = datetime.fromisoformat(row["at"])
    if at.tzinfo is None:
        raise ValueError("trace_timestamp_requires_timezone")
    duration = row.get("duration_ms")
    if type(duration) not in (float, int) or not math.isfinite(duration) or duration < 0:
        duration = None
    tool = row.get("tool", "")
    tool = tool if isinstance(tool, str) and re.fullmatch(r"[\w.:-]{1,100}", tool) else ""
    return {
        "run_id": row["run_id"], "sequence": count(row.get("sequence")),
        "at": at.astimezone(timezone.utc).isoformat(), "event": row["event"],
        "request_index": count(row.get("request_index")),
        "status": choice(row.get("status"), STATUSES, "unknown"),
        "duration_ms": duration, "tool": tool,
        "recall": recall_data(row["recall"]) if isinstance(row.get("recall"), dict) else None,
    }


def project_runs(events: list[dict], started: float) -> list[dict]:
    """Group cleaned events into run views and identify incomplete or interrupted runs.

    将已清理事件分组为运行视图，标识不完整或中断运行。
    """
    grouped: dict[str, list] = {}
    for event in events:
        grouped.setdefault(event["run_id"], []).append(event)
    runs = []
    for run_id, rows in grouped.items():
        flags: set[str] = set()
        artifacts: list[str] = []
        recalls = [r["recall"] for r in rows if r["recall"] is not None]
        for recall in recalls:
            if recall["artifact_ids"]:
                flags.add("recalled_and_injected")
            if recall["withheld_ids"]:
                flags.add("recalled_but_withheld")
            if recall["fallback"]:
                flags.add("fallback_used")
            artifacts.extend(recall["artifact_ids"] + recall["withheld_ids"] + recall["dropped_ids"])
        if recalls and not any(r["artifact_ids"] or r["picked_ids"] or r["pinned_ids"] or r["withheld_ids"] or r["dropped_ids"] for r in recalls):
            flags.add("not_recalled")
        ends = [r for r in rows if r["event"] == "agent_done"]
        delivered = any(r["event"] == "message_sent" for r in rows)
        status = "running"
        if ends:
            status = "error" if ends[-1]["status"] == "error" else "completed"
        elif delivered:
            status = "completed"
        elif datetime.fromisoformat(rows[-1]["at"]).timestamp() < started:
            status = "interrupted"
        runs.append({"id": run_id, "started_at": rows[0]["at"], "updated_at": rows[-1]["at"],
                     "status": status, "delivered": delivered, "flags": sorted(flags),
                     "artifact_ids": ids(artifacts), "event_count": len(rows),
                     "partial": any(r["sequence"] != i for i, r in enumerate(rows, 1))
                                or not any(r["event"] == "agent_begin" for r in rows)})
    return list(reversed(runs))
