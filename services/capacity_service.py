"""Observe capacity and coordinate admission/maintenance; no SQL or resource ownership.

观察容量并协调接纳和维护，不实现 SQL 或管理资源生命周期。
"""

from __future__ import annotations

import datetime
from typing import Any, Callable

try:
    from .ports import ExtractionStore, MetricsStore, CapacityTrace, ServiceJournal, ServiceLogger
    from .maintenance_service import MaintenanceService
    from ..core.domain.operations.capacity import (
        NORMAL,
        PROTECTIVE,
        CapacityDecision,
        CapacityGovernor,
        CapacitySnapshot,
    )
except ImportError:
    from services.ports import ExtractionStore, MetricsStore, CapacityTrace, ServiceJournal, ServiceLogger
    from services.maintenance_service import MaintenanceService
    from core.domain.operations.capacity import (
        NORMAL,
        PROTECTIVE,
        CapacityDecision,
        CapacityGovernor,
        CapacitySnapshot,
    )


class CapacityService:
    """Own capacity observation and admission state; delegate memory maintenance / 管理容量观察及接纳状态，将记忆维护委托给维护服务。"""

    def __init__(
        self,
        *,
        metrics: MetricsStore | None,
        extraction: ExtractionStore | None,
        maintenance: MaintenanceService,
        trace: CapacityTrace,
        journal: ServiceJournal,
        governor: CapacityGovernor,
        config: Callable[[str, Any], Any],
        logger: ServiceLogger,
        on_release: Callable[[], None] | None = None,
    ) -> None:
        self.metrics = metrics
        self.extraction = extraction
        self.maintenance = maintenance
        self.trace = trace
        self.journal = journal
        self.governor = governor
        self.config = config
        self.logger = logger
        self.on_release = on_release
        self.context_chars = 0
        self.deferred_rows = 0
        self.degrade_recall = False
        self.backpressure = False
        self._state = NORMAL
        self._action_mark = ""

    @property
    def thresholds(self):
        """Read the configured governor thresholds / 读取容量调节器的配置阈值。"""
        return self.governor.thresholds

    def set_context_chars(self, value: int) -> None:
        """Update the observed per-turn context size / 更新观察到的每轮上下文大小。"""
        self.context_chars = max(0, int(value))

    def snapshot(self) -> CapacitySnapshot:
        """Read capacity measurements without changing admission state / 读取容量用量，不改变接纳状态。"""
        usage = self.metrics.capacity_usage() if self.metrics is not None else {}
        return CapacitySnapshot(
            source_rows=int(usage.get("source_rows", 0)),
            source_bytes=int(usage.get("source_bytes", 0)),
            pending_rows=int(usage.get("pending_rows", 0)),
            pending_oldest_age_seconds=float(
                usage.get("pending_oldest_age_seconds", 0.0)
            ),
            deferred_rows=int(usage.get("deferred_rows", 0)),
            dead_rows=int(usage.get("dead_rows", 0)),
            db_bytes=int(usage.get("db_bytes", 0)),
            artifact_count=int(usage.get("artifact_count", 0)),
            artifact_bytes=int(usage.get("artifact_bytes", 0)),
            expired_artifacts=int(usage.get("expired_artifacts", 0)),
            context_chars_per_turn=self.context_chars,
            trace_rows=self.trace.count,
            trace_oldest_age_seconds=self.trace.oldest_age_seconds(),
        )

    def observe(self) -> CapacityDecision:
        """Evaluate capacity, update admission state and record state transitions / 评估容量，更新接纳状态并记录状态变化。"""
        snapshot = self.snapshot()
        decision = self.governor.evaluate(snapshot)
        self.degrade_recall = "degrade_recall" in decision.actions
        self.backpressure = "backpressure" in decision.actions
        self.deferred_rows = snapshot.deferred_rows
        if decision.state != self._state:
            self.journal.record(
                "capacity",
                "warning" if decision.state != NORMAL else "info",
                f"capacity state changed to {decision.state}",
                stage="governor",
                context={
                    "pending": snapshot.pending_rows,
                    "deferred": snapshot.deferred_rows,
                    "dead": snapshot.dead_rows,
                    "databaseBytes": snapshot.db_bytes,
                    "artifacts": snapshot.artifact_count,
                    "actions": len(decision.actions),
                    "pressure": decision.pressure,
                },
            )
            if decision.state == PROTECTIVE:
                self.logger.warning("[seekmemory] capacity entered protection")
            self.trace.record(
                "capacity",
                decision.state,
                {
                    "pending": snapshot.pending_rows,
                    "deferred": snapshot.deferred_rows,
                    "dead": snapshot.dead_rows,
                    "databaseBytes": snapshot.db_bytes,
                    "pressure": decision.pressure,
                },
            )
            self._state = decision.state
        return decision

    def admit_deferred(self) -> bool:
        """Decide whether a new deferred row fits the current limit / 判断当前上限是否允许新增延后处理行。"""
        if not self.backpressure:
            return False
        return self.deferred_rows < self.thresholds.defer_limit

    def batch_cap(self, decision: CapacityDecision) -> int:
        """Compute the extraction batch cap from the capacity decision / 根据容量决策计算抽取批次上限。"""
        cap = max(1, int(self.config("max_sessions_per_flush", 6)))
        if "raise_batch_size" in decision.actions:
            return min(24, cap * 2)
        return cap

    def apply_maintenance(self, decision: CapacityDecision) -> None:
        """Release deferred rows and execute due pressure actions in order / 释放延后处理行并依次执行到期的压力处理动作。"""
        if (
            "release_deferred" in decision.actions
            and self.deferred_rows
            and self.extraction is not None
        ):
            released = self.extraction.release_deferred(self.thresholds.release_batch)
            if released:
                self.deferred_rows = max(0, self.deferred_rows - released)
                if self.on_release is not None:
                    self.on_release()
                self.journal.record(
                    "capacity",
                    "info",
                    "deferred writes released",
                    stage="admission",
                    context={"released": released},
                )
        actions = set(decision.actions)
        actionable = {
            "compact_artifacts",
            "forget_expired",
            "trim_trace",
            "alert",
        }
        if not actionable.intersection(actions):
            return
        mark = datetime.datetime.now().strftime("%Y%m%d%H")
        if mark == self._action_mark:
            return
        self._action_mark = mark
        if "compact_artifacts" in actions:
            self.maintenance.compact_artifacts()
        if "forget_expired" in actions:
            self.maintenance.forget_expired()
        if "trim_trace" in actions:
            with self.journal.span("capacity", "trim_trace") as metrics:
                metrics["removed"] = self.trace.trim(
                    self.thresholds.trace_pressured_rows
                )
        if "alert" in actions:
            self.journal.record(
                "capacity",
                "warning",
                "capacity protection alert",
                stage="governor",
                context={"state": decision.state},
            )
        self.trace.record(
            "maintenance",
            decision.state,
            {"actions": len(actions), "deferred": self.deferred_rows},
        )

    def status(self) -> dict:
        """Read a capacity summary without applying maintenance actions / 读取容量摘要，不执行维护动作。"""
        snapshot = self.snapshot()
        decision = self.governor.evaluate(snapshot)
        queue = self.extraction.queue_counts() if self.extraction is not None else {}
        return {
            "state": decision.state,
            "actions": list(decision.actions),
            "reasons": list(decision.reasons),
            "pressure": decision.pressure,
            "snapshot": {
                "sourceRows": snapshot.source_rows,
                "sourceBytes": snapshot.source_bytes,
                "pendingRows": snapshot.pending_rows,
                "deferredRows": snapshot.deferred_rows,
                "deadRows": snapshot.dead_rows,
                "databaseBytes": snapshot.db_bytes,
                "artifactCount": snapshot.artifact_count,
                "artifactBytes": snapshot.artifact_bytes,
                "contextChars": snapshot.context_chars_per_turn,
                "traceRows": snapshot.trace_rows,
            },
            "queue": {str(key): int(value) for key, value in queue.items()},
        }
