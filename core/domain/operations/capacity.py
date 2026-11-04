"""Compute capacity actions from supplied snapshots; only threshold loading reads the environment.

根据给定快照计算容量动作，仅阈值加载读取环境变量。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, fields, replace
from typing import Any, Mapping

NORMAL = "normal"
PRESSURED = "pressured"
SATURATED = "saturated"
PROTECTIVE = "protective"

ENV_PREFIX = "SEEKMEMORY_CAPACITY_"


@dataclass(frozen=True)
class CapacityThresholds:
    """Define soft and hard limits for each resource pool.

    定义各资源池的软硬限额。
    """

    pending_pressured_rows: int = 80
    pending_saturated_rows: int = 200
    pending_protective_rows: int = 400
    pending_pressured_age_seconds: float = 12 * 60 * 60
    pending_saturated_age_seconds: float = 24 * 60 * 60
    pending_protective_age_seconds: float = 72 * 60 * 60
    artifact_pressured_count: int = 400
    artifact_saturated_count: int = 800
    artifact_pressured_bytes: int = 64 * 1024 * 1024
    artifact_saturated_bytes: int = 256 * 1024 * 1024
    context_saturated_chars: int = 4_000
    trace_pressured_rows: int = 300
    trace_pressured_age_seconds: float = 3 * 24 * 60 * 60
    trace_saturated_rows: int = 450
    trace_saturated_age_seconds: float = 7 * 24 * 60 * 60
    source_alert_bytes: int = 1024 * 1024 * 1024
    defer_limit: int = 400
    release_batch: int = 50
    extraction_max_attempts: int = 5
    deferred_pressured_rows: int = 200
    deferred_saturated_rows: int = 400
    dead_alert_rows: int = 10
    database_pressured_bytes: int = 512 * 1024 * 1024
    database_saturated_bytes: int = 1024 * 1024 * 1024
    pending_release_rows: int = 40


def _coerce(default: Any, raw: Any) -> Any:
    """Convert an override to its declared field type.

    将覆盖值转换为声明的字段类型。
    """
    if isinstance(default, bool):
        if isinstance(raw, str):
            return raw.strip().lower() in {"1", "true", "yes", "on"}
        return bool(raw)
    if isinstance(default, float):
        return float(raw)
    if isinstance(default, int):
        return int(float(raw))
    return raw


def load_thresholds(
    values: Mapping[str, Any] | None = None,
    *,
    env_prefix: str = ENV_PREFIX,
) -> CapacityThresholds:
    """Resolve defaults, environment and mapping overrides in order; invalid values retain defaults. Environment keys use SEEKMEMORY_CAPACITY_<FIELD_NAME>.

    依次解析默认值、环境变量及映射覆盖，无效值保留默认值。环境变量使用 SEEKMEMORY_CAPACITY_<FIELD_NAME>。
    """
    base = CapacityThresholds()
    names = {field.name for field in fields(CapacityThresholds)}
    raw: dict[str, Any] = {}
    for name in names:
        key = f"{env_prefix}{name.upper()}"
        if key in os.environ:
            raw[name] = os.environ[key]
    for key, value in (values or {}).items():
        if str(key) in names:
            raw[str(key)] = value
    updates = {}
    for name, value in raw.items():
        try:
            updates[name] = _coerce(getattr(base, name), value)
        except (TypeError, ValueError):
            continue
    return replace(base, **updates) if updates else base


@dataclass(frozen=True)
class CapacitySnapshot:
    """Describe current Source, pending, Artifact, context and trace usage.

    描述当前 Source、待处理、Artifact、上下文及追踪用量。
    """

    source_rows: int = 0
    source_bytes: int = 0
    pending_rows: int = 0
    pending_oldest_age_seconds: float = 0.0
    deferred_rows: int = 0
    dead_rows: int = 0
    db_bytes: int = 0
    artifact_count: int = 0
    artifact_bytes: int = 0
    expired_artifacts: int = 0
    context_chars_per_turn: int = 0
    trace_rows: int = 0
    trace_oldest_age_seconds: float = 0.0


@dataclass(frozen=True)
class CapacityDecision:
    """Return pressure and ordered scheduling actions without executing them.

    返回压力及有序调度动作，不执行这些动作。
    """

    state: str
    actions: tuple[str, ...]
    reasons: tuple[str, ...] = ()
    pressure: float = 0.0


class CapacityGovernor:
    """Evaluate capacity snapshots without I/O or resource ownership.

    评估容量快照，不执行读写或拥有资源。
    """

    def __init__(self, thresholds: CapacityThresholds | None = None) -> None:
        self.thresholds = thresholds or CapacityThresholds()

    def evaluate(self, snapshot: CapacitySnapshot) -> CapacityDecision:
        """Return a deterministic decision for the supplied usage snapshot.

        为给定用量快照返回确定性决策。
        """
        limits = self.thresholds
        state = NORMAL
        reasons: list[str] = []

        pending_soft = (
            snapshot.pending_rows >= limits.pending_pressured_rows
            or snapshot.pending_oldest_age_seconds
            >= limits.pending_pressured_age_seconds
        )
        pending_hard = (
            snapshot.pending_rows >= limits.pending_saturated_rows
            or snapshot.pending_oldest_age_seconds
            >= limits.pending_saturated_age_seconds
        )
        pending_protective = (
            snapshot.pending_rows >= limits.pending_protective_rows
            or snapshot.pending_oldest_age_seconds
            >= limits.pending_protective_age_seconds
        )
        deferred_soft = snapshot.deferred_rows >= limits.deferred_pressured_rows
        deferred_hard = snapshot.deferred_rows >= limits.deferred_saturated_rows
        db_soft = snapshot.db_bytes >= limits.database_pressured_bytes
        db_hard = snapshot.db_bytes >= limits.database_saturated_bytes
        dead_alert = snapshot.dead_rows >= limits.dead_alert_rows

        artifact_soft = (
            snapshot.artifact_count >= limits.artifact_pressured_count
            or snapshot.artifact_bytes >= limits.artifact_pressured_bytes
        )
        artifact_hard = (
            snapshot.artifact_count >= limits.artifact_saturated_count
            or snapshot.artifact_bytes >= limits.artifact_saturated_bytes
        )
        trace_soft = (
            snapshot.trace_rows >= limits.trace_pressured_rows
            or snapshot.trace_oldest_age_seconds
            >= limits.trace_pressured_age_seconds
        )
        trace_hard = (
            snapshot.trace_rows >= limits.trace_saturated_rows
            or snapshot.trace_oldest_age_seconds
            >= limits.trace_saturated_age_seconds
        )
        source_protective = snapshot.source_bytes >= limits.source_alert_bytes
        context_hard = (
            snapshot.context_chars_per_turn >= limits.context_saturated_chars
        )

        if pending_soft or artifact_soft or trace_soft or deferred_soft or db_soft or dead_alert:
            state = PRESSURED
        if pending_hard or artifact_hard or trace_hard or context_hard or deferred_hard or db_hard:
            state = SATURATED
        if pending_protective or source_protective:
            state = PROTECTIVE

        if pending_soft:
            reasons.append(f"pending:{snapshot.pending_rows}rows")
        if artifact_soft:
            reasons.append(f"artifact:{snapshot.artifact_count}/{snapshot.artifact_bytes}bytes")
        if deferred_soft:
            reasons.append(f"deferred:{snapshot.deferred_rows}rows")
        if db_soft:
            reasons.append(f"database:{snapshot.db_bytes}bytes")
        if dead_alert:
            reasons.append(f"dead:{snapshot.dead_rows}rows")
        if context_hard:
            reasons.append(f"context:{snapshot.context_chars_per_turn}chars")
        if trace_hard:
            reasons.append(f"trace:{snapshot.trace_rows}rows")
        if source_protective:
            reasons.append(f"source:{snapshot.source_bytes}bytes")

        actions: list[str] = []
        if snapshot.pending_rows:
            actions.append("schedule_extraction")
        if (snapshot.deferred_rows and snapshot.pending_rows < limits.pending_release_rows
                and not pending_soft):
            actions.append("release_deferred")
        if pending_soft:
            actions.append("raise_batch_size")
        if pending_hard or deferred_hard:
            actions.append("backpressure")
        if artifact_soft:
            actions.append("compact_artifacts")
        if artifact_hard or snapshot.expired_artifacts:
            actions.append("forget_expired")
        if context_hard:
            actions.append("degrade_recall")
        if trace_hard:
            actions.append("trim_trace")
        if state == PROTECTIVE or dead_alert:
            actions.append("alert")

        pressure = max(
            snapshot.pending_rows / max(1, limits.pending_saturated_rows),
            snapshot.deferred_rows / max(1, limits.deferred_saturated_rows),
            snapshot.artifact_count / max(1, limits.artifact_saturated_count),
            snapshot.trace_rows / max(1, limits.trace_saturated_rows),
            snapshot.context_chars_per_turn / max(1, limits.context_saturated_chars),
            snapshot.source_bytes / max(1, limits.source_alert_bytes),
            snapshot.db_bytes / max(1, limits.database_saturated_bytes),
        )
        return CapacityDecision(
            state, tuple(actions), tuple(reasons), round(min(1.0, pressure), 3)
        )
