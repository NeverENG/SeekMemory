"""Run evidence-backed persona maintenance after durable extraction commits."""
from __future__ import annotations

import time

from core.domain.character.bot_behavior import MIN_EVIDENCE
from core.domain.memory.versioning import VersionError
from maintain.persona import distill_self_persona
from maintain.self_impression import build_self_impressions
from maintain.self_impression_policy import evidence_counts
from maintain.writer import MaintenanceWriter

# A full reconciliation walks every active memory and its Sources. Host polls
# respect this interval; a new durable extraction commit runs maintenance now.
DEFAULT_MIN_INTERVAL_S = 30.0


class PersonaEvolutionService:
    """Keep one writer and retry interrupted maintenance without model calls."""

    def __init__(self, artifacts, sources, cache, *,
                 min_interval_s: float = DEFAULT_MIN_INTERVAL_S) -> None:
        self.artifacts = artifacts
        self.sources = sources
        self.cache = cache
        self.min_interval_s = max(0.0, float(min_interval_s))
        self.writer = MaintenanceWriter(artifacts, cache)
        self.dirty = True  # Reconcile evidence left by an interrupted process.
        self.degraded = False
        self.last_error = ""
        self.next_attempt = 0.0
        self.failures = 0
        # Read-only explanation for the last run: a no-op is a legal result, so
        # it must be distinguishable from "maintenance could not see evidence".
        # 上一次运行的可读解释：no-op 是合法结果，必须能和"看不见证据"区分开。
        self.min_evidence = MIN_EVIDENCE
        self.evidence: dict[str, int] = {}
        self.last_writes = 0
        self.last_persona = ""
        self.evidence_error = ""

    def after_extraction(self) -> None:
        self.dirty = True
        # Fresh durable evidence must not inherit a previous successful no-op's
        # coalescing delay. Keep failure backoff intact while degraded.
        if not self.degraded:
            self.next_attempt = 0.0
        self.maybe_run()

    def maybe_run(self) -> bool:
        """Run when dirty and due; failures back off, new commits run promptly."""
        if not self.dirty or time.monotonic() < self.next_attempt:
            return False
        for attempt in range(2):
            try:
                self.writer.ensure_ready()
                writes = build_self_impressions(self.artifacts, self.sources, self.cache,
                                                writer=self.writer)
                persona = distill_self_persona(self.artifacts, self.sources, self.cache,
                                               writer=self.writer)
            except VersionError as exc:
                # Never replay a stale plan; rebuild from durable heads.
                self.last_error = f"VersionError: {exc}"
                if attempt == 0:
                    try:
                        self.cache.load()
                    except Exception:
                        break
                    continue
                break
            except Exception as exc:
                self.last_error = f"{type(exc).__name__}: {exc}"
                break
            self.last_writes = int(writes)
            self.last_persona = persona.header.id if persona is not None else ""
            self.dirty = False
            self.degraded = False
            self.last_error = ""
            self.failures = 0
            self.next_attempt = time.monotonic() + self.min_interval_s
            self._observe_evidence()
            return True
        self.degraded = True
        self.failures += 1
        self.next_attempt = time.monotonic() + self._backoff()
        return False

    def record_failure(self, error: BaseException) -> None:
        """Record a maintenance failure without touching the committed extraction.

        记录维护失败，不改变已完成的抽取结果；抽取成功绝不因此变成 500。
        """
        self.last_error = f"{type(error).__name__}: {error}"
        self.degraded = True
        self.failures += 1
        self.next_attempt = time.monotonic() + self._backoff()

    def diagnostics(self) -> dict:
        """Read the last run's evidence counts for this kernel's `/status`.

        读取上次运行的证据计数，供本机内核 `/status` 只读展示。
        """
        return {
            "min_evidence": self.min_evidence,
            "evidence": dict(self.evidence),
            "needed_by_behavior": {
                kind: max(0, self.min_evidence - count)
                for kind, count in self.evidence.items()
            },
            "last_writes": self.last_writes,
            "last_persona": self.last_persona,
            "evidence_error": self.evidence_error,
        }

    def _observe_evidence(self) -> None:
        """Count per-category observations after a run; never raise into callers.

        运行后统计各类别观察数；统计失败不得向调用方抛错，也不影响维护结果。
        """
        try:
            pool = self.cache.active("memory")
            ids = sorted({sid for art in pool for sid in art.header.lineage.sources})
            self.evidence = evidence_counts(pool, self.sources.sources_by_ids(ids))
            self.evidence_error = ""
        except Exception as exc:  # Diagnostics must stay outside the write path.
            self.evidence_error = f"{type(exc).__name__}: {exc}"

    def _backoff(self) -> float:
        """Read this attempt's retry delay without changing counters."""
        return max(self.min_interval_s,
                   min(300.0, 5.0 * 2 ** min(self.failures - 1, 6)))
