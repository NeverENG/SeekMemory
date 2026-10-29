"""Orchestrate memory maintenance and persona evolution over injected resources.

在注入的资源上编排记忆维护和人格演化，不管理资源生命周期。
"""

from __future__ import annotations

import datetime
from typing import Any, Callable

try:
    from ..app.persona_synthesis import (
        PersonaEvidence,
        build_persona_request,
        parse_persona_draft,
    )
    from .ports import ArtifactCache, ArtifactStore, SourceStore, PersonaModelFactory, ServiceJournal, ServiceLogger
    from ..core.bot_behavior import SELF_SUBJECT
    from ..core.persona import PERSONA_SYNTHESIS_VERSION
except ImportError:  # Standalone root / 独立测试以仓库为导入根。
    from app.persona_synthesis import (
        PersonaEvidence,
        build_persona_request,
        parse_persona_draft,
    )
    from services.ports import ArtifactCache, ArtifactStore, SourceStore, PersonaModelFactory, ServiceJournal, ServiceLogger
    from core.bot_behavior import SELF_SUBJECT
    from core.persona import PERSONA_SYNTHESIS_VERSION


try:
    from ..maintain.writer import MaintenanceWriter
    from ..app.cache_repair import CacheRepairs
    from ..maintain.plans import RevisionPlan, RevisionWrite
    from ..maintain.merge_policy import DEFAULT_MERGE_THRESHOLD
except ImportError:
    from maintain.writer import MaintenanceWriter
    from app.cache_repair import CacheRepairs
    from maintain.plans import RevisionPlan, RevisionWrite
    from maintain.merge_policy import DEFAULT_MERGE_THRESHOLD

from .persona_policy import persona_evidence, persona_revision, relationship_weight


class MaintenanceService:
    """Orchestrate maintenance and persona model calls over caller-owned resources / 在调用方管理的资源上编排维护及人格模型调用。"""

    def __init__(
        self,
        *,
        artifacts: ArtifactStore | None,
        sources: SourceStore | None,
        cache: ArtifactCache | None,
        journal: ServiceJournal,
        task_id: Callable[[], str],
        logger: ServiceLogger,
        config: Callable[[str, Any], Any] | None = None,
        persona_model: PersonaModelFactory | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
        cache_repairs: CacheRepairs | None = None,
    ) -> None:
        self.artifacts = artifacts
        self.sources = sources
        self.cache = cache
        self.journal = journal
        self.task_id = task_id
        self.logger = logger
        self._c = config or (lambda _key, default: default)
        self.persona_model = persona_model
        self.clock = clock or datetime.datetime.now
        self._writer = MaintenanceWriter(artifacts, cache, defer_cache_errors=True, cache_repairs=cache_repairs)

    @property
    def _writes(self) -> MaintenanceWriter:
        """Bind current caller-owned resources without losing prepared progress.

        绑定当前调用方资源，不丢失已准备进度；兼容调用方重建连接及缓存后的重新接线。
        """
        self._writer.artifacts = self.artifacts
        self._writer.cache = self.cache
        return self._writer

    def _relationship_mode(self) -> str:
        """Read the relationship mode, warning and falling back when invalid / 读取关系模式，无效时警告并回退。"""
        mode = str(self._c("relationship_mode", "observe") or "").strip().lower()
        if mode in ("off", "observe", "enforce"):
            return mode
        self.logger.warning("[seekmemory] invalid relationship config: relationship_mode")
        return "observe"

    def _relationship_weight(self, key: str, default: float) -> float:
        """Normalize a configured weight and report corrections / 规范化配置权重并报告纠正。"""
        normalized = relationship_weight(self._c(key, default), default)
        if normalized.corrected:
            self.logger.warning(f"[seekmemory] clamped relationship config: {key}")
        return normalized.value

    def _relationship_policy(self):
        """Build the relationship policy from normalized configuration weights / 按规范化后的配置权重构造关系规则。"""
        try:
            from ..core.relationship_rules import RelationshipScoringPolicy
        except ImportError:
            from core.relationship_rules import RelationshipScoringPolicy
        private_weight = self._relationship_weight(
            "relationship_private_weight", 1.0
        )
        group_weight = self._relationship_weight(
            "relationship_group_weight", 0.5
        )
        return RelationshipScoringPolicy(
            private_weight=private_weight,
            group_weight=group_weight,
            unknown_weight=group_weight,
        )

    def retry_writebacks(self) -> int:
        """Resume prepared maintenance commits/cache repairs without policy or model calls.

        不调用规则或模型，仅恢复已准备的维护提交及缓存补偿。
        """
        return self._writes.retry_writebacks()

    async def weekly(self) -> dict:
        """Run the ordered relationship, self-impression, decay, merge and persona stages / 依次执行关系、自身印象、衰退、合并及人格阶段。"""
        try:
            from ..maintain.decay import decay_all
            from ..maintain.merge import merge_similar
            from ..maintain.persona import distill_self_persona
            from ..maintain.self_impression import build_self_impressions
            from ..maintain.relationship import consolidate_relationships
        except ImportError:
            from maintain.decay import decay_all
            from maintain.merge import merge_similar
            from maintain.persona import distill_self_persona
            from maintain.self_impression import build_self_impressions
            from maintain.relationship import consolidate_relationships

        if self.artifacts is None or self.sources is None or self.cache is None:
            return {}
        self._writes.ensure_ready()
        today = datetime.date.today().isoformat()
        relationships = 0
        if self._relationship_mode() != "off":
            with self.journal.span("weekly", "relationship") as metrics:
                relationships = consolidate_relationships(
                    self.artifacts,
                    self.sources,
                    self.cache,
                    self._relationship_policy(), writer=self._writes,
                )
                metrics["updated"] = relationships
        with self.journal.span("weekly", "self_impression") as metrics:
            self_made = build_self_impressions(self.artifacts, self.sources, self.cache, today=today, writer=self._writes)
            metrics["made"] = self_made
        with self.journal.span("weekly", "decay") as metrics:
            dropped = decay_all(self.artifacts, self.cache, today, writer=self._writes)
            metrics["forgotten"] = dropped
        with self.journal.span("weekly", "merge", threshold=DEFAULT_MERGE_THRESHOLD) as metrics:
            merged = merge_similar(self.artifacts, self.cache, threshold=DEFAULT_MERGE_THRESHOLD, writer=self._writes)
            metrics["merged"] = merged
        with self.journal.span("weekly", "persona") as metrics:
            if self.persona_model is None:
                persona = distill_self_persona(self.artifacts, self.sources, self.cache, today, writer=self._writes)
                persona_result = {
                    "status": "updated" if persona else "unchanged",
                    "mode": "legacy_deterministic",
                }
            else:
                persona_result = await self._synthesize_persona_async()
                persona = persona_result.get("status") == "updated"
                if not persona and persona_result.get("status") in (
                    "no_persona", "not_bootstrapped"
                ):
                    # Backward-compatible transition for legacy installs: if
                    # there is no seeded persona to synthesize from, keep the
                    # historical deterministic self-impression persona path.
                    persona = distill_self_persona(
                        self.artifacts, self.sources, self.cache, today, writer=self._writes
                    )
                    persona_result = {
                        "status": "updated" if persona else "unchanged",
                        "mode": "legacy_deterministic_fallback",
                        "synthesis": persona_result,
                    }
            metrics.update(persona_result)
        self.journal.record(
            "weekly",
            "info",
            f"relationships {relationships}, forgot {dropped}, merged {merged}, persona: {persona_result.get('status', 'unchanged')}",
            self.task_id(),
        )
        self.logger.info(
            f"[seekmemory] weekly maintenance: relationships {relationships}, "
            f"forgot {dropped}, merged {merged}, "
            f"persona {persona_result.get('status', 'unchanged')}"
        )
        return {
            "forgotten": dropped,
            "merged": merged,
            "self_impressions": self_made,
            "persona": bool(persona),
            "persona_result": persona_result,
            "relationships": relationships,
            "writeback_pending": self._writes.pending(),
        }

    async def _synthesize_persona_async(self) -> dict:
        """Select evidence, request a draft and commit before updating cache / 选择证据并请求草案，提交后再更新缓存。"""
        self._writes.ensure_ready()
        if not bool(self._c("persona_synthesis_enabled", True)):
            return {"status": "disabled"}
        active = sorted(
            self.cache.active("persona"),
            key=lambda art: (
                int(art.header.revision or 0),
                str(art.header.time.updated or ""),
                art.header.id,
            ),
        )
        if not active:
            return {"status": "no_persona"}
        current = active[-1]
        payload = current.payload
        if not str(payload.get("text") or "").strip():
            return {"status": "empty_persona"}
        if not (payload.get("origin") or payload.get("seed_id")):
            return {"status": "not_bootstrapped"}
        interval_days = max(0, int(self._c("persona_synthesis_interval_days", 7)))
        age_days = self._persona_age_days(current)
        if interval_days and age_days is not None and age_days < interval_days:
            return {
                "status": "not_due",
                "age_days": round(age_days, 3),
                "interval_days": interval_days,
            }
        evidence = self._persona_evidence()
        if not evidence:
            return {"status": "no_evidence"}
        if not any(item.source_ids for item in evidence):
            return {"status": "no_sources"}
        try:
            model = await self.persona_model()  # type: ignore[misc]
            request = build_persona_request(
                payload,
                evidence,
                max_evidence_chars=max(
                    200, int(self._c("persona_synthesis_evidence_chars", 2400))
                ),
            )
            response = await model.complete(request)
            draft = parse_persona_draft(
                str(getattr(response, "text", "") or ""), payload
            )
        except Exception as exc:  # noqa: BLE001 - keep the old persona on failure
            self.logger.warning(
                f"[seekmemory] persona synthesis failed: {type(exc).__name__}"
            )
            return {"status": "failed", "error": type(exc).__name__}
        if draft is None:
            return {"status": "unchanged", "reason": "same_text"}
        try:
            replacement = self._persona_revision(current, draft, evidence)
            plan = RevisionPlan((RevisionWrite(
                replacement, current.header.revision, tuple(replacement.header.lineage.sources),
            ),), "revise", "dream persona synthesis")
            self._writes.execute(plan, grouped=False)
        except Exception as exc:  # noqa: BLE001 - no partial persona write
            self.logger.warning(
                f"[seekmemory] persona synthesis write failed: {type(exc).__name__}"
            )
            return {"status": "failed", "error": type(exc).__name__}
        return {
            "status": "updated",
            "writeback_pending": self._writes.pending(),
            "revision": replacement.header.revision,
            "evidence": len(evidence),
            "usage": {
                "in": int(getattr(response, "usage_in", 0) or 0),
                "cached": int(getattr(response, "usage_cached", 0) or 0),
                "out": int(getattr(response, "usage_out", 0) or 0),
            },
        }

    def _persona_age_days(self, current) -> float | None:
        """Read persona age with the existing timezone-alignment behavior / 沿用现有时区对齐行为读取人格年龄。"""
        raw = str(current.header.time.updated or "")
        if not raw:
            return None
        try:
            last = datetime.datetime.fromisoformat(raw)
        except ValueError:
            return None
        now = self.clock()
        if last.tzinfo is not None and now.tzinfo is None:
            now = now.replace(tzinfo=last.tzinfo)
        elif last.tzinfo is None and now.tzinfo is not None:
            last = last.replace(tzinfo=now.tzinfo)
        return max(0.0, (now - last).total_seconds() / 86400.0)

    def _persona_evidence(self) -> list[PersonaEvidence]:
        """Read candidate evidence, then apply pure visibility rules / 读取候选证据，再应用纯可见性规则。"""
        try:
            from ..maintain.self_impression import promote_self_candidates
        except ImportError:
            from maintain.self_impression import promote_self_candidates
        return persona_evidence(
            promote_self_candidates(self.cache, self.sources), self.cache.active(),
            max(1, int(self._c("persona_synthesis_evidence_limit", 8))),
        )

    def _persona_revision(self, current, draft: dict, evidence: list[PersonaEvidence]) -> Any:
        """Prepare a revision without writing it / 准备版本，不执行写入。"""
        return persona_revision(current, draft, evidence)

    def compact_artifacts(self) -> int:
        """Merge similar active memories through the existing maintenance writer / 通过现有维护写入流程合并相似的有效记忆。"""
        try:
            from ..maintain.merge import merge_similar
        except ImportError:
            from maintain.merge import merge_similar
        if self.artifacts is None or self.cache is None:
            return 0
        with self.journal.span("capacity", "compact_artifacts") as metrics:
            merged = merge_similar(self.artifacts, self.cache, threshold=DEFAULT_MERGE_THRESHOLD, writer=self._writes)
            metrics["merged"] = merged
        return merged

    def forget_expired(self, today: str = "") -> int:
        """Forget expired memories through the existing maintenance writer / 通过现有维护写入流程遗忘过期记忆。"""
        try:
            from ..maintain.lifecycle import forget_expired
        except ImportError:
            from maintain.lifecycle import forget_expired
        if self.artifacts is None or self.cache is None:
            return 0
        with self.journal.span("capacity", "forget_expired") as metrics:
            forgotten = forget_expired(self.artifacts, self.cache, today, writer=self._writes)
            metrics["forgotten"] = forgotten
        return forgotten
