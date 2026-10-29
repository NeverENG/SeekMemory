"""Coordinate pending extraction, model usage and ordered memory writes.

协调待处理抽取、模型用量及有顺序的记忆写入，资源由调用方管理。
"""

from __future__ import annotations

import asyncio
import datetime
import re
from dataclasses import replace
from functools import partial
from contextlib import AbstractContextManager, nullcontext
from typing import Any, Callable
from collections.abc import Iterable

try:
    from ..app.budget import estimate_tokens
    from ..app.contracts import ChatRequest, DialogueTurn, WriteOutcome, ExtractionFailure
    from ..app.flush_policy import (
        decide_flush,
        select_topic_batches,
    )
    from .ports import ArtifactCache, ArtifactStore, ExtractionStore, SourceStore, PendingBuffer, ServiceJournal, ServiceLogger, ProviderFactory, ChatModel, LegacyTextModel
    from ..core.graph import Graph
    from ..core.artifact import content_of, revise
    from ..core.capacity import PROTECTIVE, SATURATED
    from ..maintain.impression import revise_impression
    from ..maintain.link import link_new
    from ..perceive.absorb import ExtractionPlan, build_plan, dialogue_of, recover_parents, worth_now
    from ..perceive.extract import build_prompt
    from ..perceive.importance import (
        MIN_IMPORTANCE_SCORE,
        TopicImportance,
        rank_topics,
        select_important_topics,
        select_ranked_topics,
    )
    from ..perceive.model import ProviderChatModel
except ImportError:
    from app.budget import estimate_tokens
    from app.contracts import ChatRequest, DialogueTurn, WriteOutcome, ExtractionFailure
    from app.flush_policy import (
        decide_flush,
        select_topic_batches,
    )
    from services.ports import ArtifactCache, ArtifactStore, ExtractionStore, SourceStore, PendingBuffer, ServiceJournal, ServiceLogger, ProviderFactory, ChatModel, LegacyTextModel
    from core.graph import Graph
    from core.artifact import content_of, revise
    from core.capacity import PROTECTIVE, SATURATED
    from maintain.impression import revise_impression
    from maintain.link import link_new
    from perceive.absorb import ExtractionPlan, build_plan, dialogue_of, recover_parents, worth_now
    from perceive.extract import build_prompt
    from perceive.importance import (
        MIN_IMPORTANCE_SCORE,
        TopicImportance,
        rank_topics,
        select_important_topics,
        select_ranked_topics,
    )
    from perceive.model import ProviderChatModel


from .diagnostics import diagnostic, span
from .ingest_state import PreparedExtraction
from .ingest_selection import ReadyTopic, ResolvedBatch, group_batches, budget_reached


class IngestService:
    """Own extraction and its write stages; scheduling and resources belong to callers / 管理抽取及其写入阶段，调度与资源由调用方负责。"""

    def __init__(
        self,
        *,
        buffer: PendingBuffer | None,
        artifacts: ArtifactStore | None,
        sources: SourceStore | None,
        extraction: ExtractionStore | None,
        cache: ArtifactCache | None,
        graph: Graph | None,
        journal: ServiceJournal | None,
        config: Callable[[str, Any], Any],
        provider_for: ProviderFactory,
        owner_id: Callable[[], str],
        logger: ServiceLogger,
    ) -> None:
        self.buffer = buffer
        self.artifacts = artifacts
        self.sources = sources
        self.extraction = extraction
        self.cache = cache
        self.graph = graph
        self.journal = journal
        self.config = config
        self.provider_for = provider_for
        self.owner_id = owner_id
        self.logger = logger
        self.flushing = False
        self.flush_day = ""
        self.flush_count = 0
        self._usage_calls = 0
        self._usage_in = 0
        self._usage_cached = 0
        self._usage_out = 0
        self._prepared: dict[tuple[DialogueTurn, ...], PreparedExtraction] = {}
        self._extract_lock = asyncio.Lock()
        self._retrying = False
        self._committed_total = 0

    def usage_snapshot(self) -> dict[str, int]:
        """Read cumulative content-free model usage counters / 读取不含正文的累计模型用量。"""
        return {
            "calls": int(self._usage_calls),
            "in": int(self._usage_in),
            "cached": int(self._usage_cached),
            "out": int(self._usage_out),
        }

    @staticmethod
    def _response_usage(response: Any) -> tuple[int, int, int]:
        """Normalize either supported provider usage shape / 规范化两种受支持的供应商用量结构。"""
        def number(value: Any) -> int:
            try:
                return max(0, int(value or 0))
            except (TypeError, ValueError):
                return 0

        usage = getattr(response, "usage", None)
        if usage is None:
            return (
                number(getattr(response, "usage_in", 0)),
                number(getattr(response, "usage_cached", 0)),
                number(getattr(response, "usage_out", 0)),
            )
        return (
            number(getattr(usage, "input", 0)),
            number(getattr(usage, "input_cached", 0)),
            number(getattr(usage, "output", 0)),
        )

    def _record_usage(self, usage: tuple[int, int, int]) -> None:
        """Accumulate usage after a completed model call / 在模型调用完成后累计用量。"""
        self._usage_calls += 1
        self._usage_in += max(0, int(usage[0]))
        self._usage_cached += max(0, int(usage[1]))
        self._usage_out += max(0, int(usage[2]))

    @staticmethod
    def _with_usage(outcome: WriteOutcome, usage: tuple[int, int, int]) -> WriteOutcome:
        """Attach the completed call usage to the write outcome / 将已完成调用的用量附到写入结果。"""
        return replace(
            outcome,
            usage_in=max(0, int(usage[0])),
            usage_cached=max(0, int(usage[1])),
            usage_out=max(0, int(usage[2])),
        )

    def should_flush(
        self,
        *,
        capacity_state: str,
        capacity_actions,
        dream_only: bool,
    ) -> bool:
        """Evaluate pending-input and capacity gates without starting extraction / 评估待处理输入与容量条件，不启动抽取。"""
        if self.flushing or self.buffer is None or self.extraction is None:
            return False
        today = datetime.date.today().isoformat()
        if self.flush_day != today:
            self.flush_day, self.flush_count = today, 0
        decision = decide_flush(
            pending=len(self.buffer.items),
            idle_seconds=self.buffer.idle_seconds(),
            worth_now=worth_now(self.buffer.items),
            flushes_today=self.flush_count,
            idle_flush_seconds=float(self.config("idle_flush_seconds", 0)),
            min_pending=int(self.config("min_pending", 8)),
            max_flushes_per_day=int(self.config("max_flushes_per_day", 2)),
            backlog_flush_at=int(self.config("backlog_flush_at", 30)),
            topic_age_seconds=self.buffer.oldest_topic_age(),
            topic_ttl_seconds=float(self.config("topic_ttl_seconds", 86400)),
            dream_only=dream_only,
        )
        if decision.should:
            return True
        if dream_only:
            return False
        return (
            capacity_state in (SATURATED, PROTECTIVE)
            and "schedule_extraction" in set(capacity_actions)
        )

    def split_topics(
        self,
        items: list[DialogueTurn],
        cap: int | None = None,
        triage: bool = False,
        ranked: list[TopicImportance] | None = None,
    ) -> list[tuple[str, str, list[DialogueTurn]]]:
        """Select bounded topic groups with optional importance ranking / 选择有数量上限的话题组，可按重要性排序。"""
        limit = int(cap or self.config("max_sessions_per_flush", 6))
        if triage:
            if ranked is None:
                return select_important_topics(items, limit)
            return select_ranked_topics(ranked, limit)
        return select_topic_batches(items, limit)

    async def flush(
        self,
        reason: str,
        *,
        limit: int = 0,
        batch_cap: int = 6,
        max_attempts: int = 5,
        max_calls: int = 0,
        max_tokens: int = 0,
        triage: bool = False,
    ) -> tuple[int, int]:
        """Recover writes, select ready work and execute bounded extraction groups.

        先恢复写入，再选择可处理任务并执行限量抽取分组；模型失败保留待处理输入。
        """
        if self.flushing or self.buffer is None or self.extraction is None:
            return 0, 0
        self.flushing = True
        try:
            before = self._committed_total
            recovered_topics = self.retry_writebacks()
            written = self._committed_total - before
            pending = [row for row in self.buffer.items if not self._reserved([row])]
            if not pending:
                return written, recovered_topics
            ranked = rank_topics(pending) if triage else None
            topics = self.split_topics(pending, cap=limit or batch_cap, triage=triage, ranked=ranked)
            triage_metrics: dict[str, int] = {}
            if triage:
                eligible = sum(1 for item in ranked if item.score >= MIN_IMPORTANCE_SCORE)
                triage_metrics = {
                    "candidates": len(ranked), "eligible": eligible, "selected": len(topics),
                    "skipped_low_value": len(ranked) - eligible,
                }
            ready, failure = await self._resolve_topics(topics, max_attempts=max_attempts)
            if not ready:
                if failure is not None:
                    raise failure
                if triage_metrics:
                    diagnostic(self.journal.record, "extract", "info", "triage selected no extractable topics",
                                        context=triage_metrics, stage="triage")
                return written, recovered_topics
            self.flush_count += 1
            usage_base = self.usage_snapshot()
            groups = group_batches(
                ready, triage=triage,
                token_limit=max(1, int(self.config("dream_batch_tokens", 6000))) if triage else 0,
                fixed_tokens=estimate_tokens(len(build_prompt([], require_evidence=True))) if triage else 0,
            )
            calls = 0
            attempted: set[tuple[str, str]] = set()
            stopped = False
            for group in groups:
                for resolved in group.batches:
                    if budget_reached(calls=calls, max_calls=max_calls, max_tokens=max_tokens,
                                      base=usage_base, current=self.usage_snapshot()):
                        stopped = True
                        break
                    batch = resolved.batch
                    attempted.update((batch.session_id, topic) for topic in batch.topics)
                    calls += 1
                    try:
                        outcome = await self._run_batch(resolved, triage=triage)
                        written += outcome.written
                        if outcome.model_failed or outcome.retryable:
                            raise RuntimeError("extraction failed; keep pending input")
                    except Exception as exc:
                        if not self._reserved(batch.rows):
                            self.buffer.mark_failed(batch.rows, type(exc).__name__, max_attempts=max_attempts)
                        failure = failure or exc
                        # Triage stops the whole flush; ordinary chunks stop only their topic.
                        # 重要性筛选批次停止整次抽取，普通分块仅停止所属话题。
                        stopped = triage
                        break
                    diagnostic(self.logger.info, f"[seekmemory] {reason} extract: {len(batch.topics)} topics, "
                                     f"{len(batch.rows)} turns, {outcome.written} written")
                if stopped:
                    break
            processed = recovered_topics + len(attempted)
            if triage:
                triage_metrics.update(batches=calls, calls=calls)
            diagnostic(self.journal.record,
                "extract", "info", f"tried {processed} topics, wrote {written} memories",
                context={"topics": processed, "written": written, **triage_metrics}, stage="batch.complete",
            )
            if failure is not None:
                if written:
                    raise ExtractionFailure(written, processed, type(failure).__name__) from failure
                raise failure
            return written, processed
        finally:
            self.flushing = False

    async def _resolve_topics(self, topics: list[tuple[str, str, list[DialogueTurn]]], *, max_attempts: int) -> tuple[list[ReadyTopic], Exception | None]:
        """Resolve providers after queue readiness filtering; retain failed input.

        按队列就绪状态筛选后解析提供方，失败输入保留待处理。
        """
        ready_ids = self.extraction.ready_extraction_ids()
        ready: list[ReadyTopic] = []
        failure: Exception | None = None
        for session_id, topic_id, part in topics:
            rows = [turn for turn in part if not turn.source_id or turn.source_id in ready_ids]
            if not rows:
                continue
            try:
                with span(self.journal.span, "extract", "provider.resolve", session=session_id, topic=topic_id):
                    provider = await self.provider_for(session_id or None)
            except Exception as exc:
                self.buffer.mark_failed(rows, type(exc).__name__, max_attempts=max_attempts)
                failure = failure or exc
                continue
            if not provider:
                diagnostic(self.journal.record,
                    "extract", "warning", "provider is not configured; keeping pending input",
                    stage="provider.resolve", context={"session": session_id, "topic": topic_id},
                )
                continue
            ready.append(ReadyTopic(session_id, topic_id, rows, provider))
        return ready, failure

    async def _run_batch(self, resolved: ResolvedBatch, *, triage: bool) -> WriteOutcome:
        """Run one batch with the existing prompt rules and explicit queue confirmation.

        按既有提示词规则执行一个批次，并明确请求队列确认。
        """
        batch = resolved.batch
        metadata = {"topics": len(batch.topics)} if triage else {"topic": batch.topics[0]}
        with span(self.journal.span, "extract", "topic.extract", session=batch.session_id,
                               messages=len(batch.rows), **metadata) as metrics:
            outcome = await self.extract(
                batch.rows, ProviderChatModel(resolved.provider),
                log=partial(diagnostic, self.journal.record, "extract", "warning"), strict=True, confirm_queue=True,
                stage=partial(span, self.journal.span, "extract"),
                include_topic=triage and len(batch.topics) > 1,
                require_evidence=triage and len(batch.topics) > 1,
            )
            metrics.update(written=outcome.written, skipped=outcome.skipped,
                           usage_in=outcome.usage_in, usage_cached=outcome.usage_cached,
                           usage_out=outcome.usage_out)
        return outcome

    async def extract(
        self,
        items: Iterable[DialogueTurn] | None,
        model: ChatModel | LegacyTextModel | None,
        *,
        owner_id: str | None = None,
        log: Callable[[str], None] = lambda _msg: None,
        strict: bool = False,
        include_topic: bool = False,
        require_evidence: bool = False,
        confirm_queue: bool = False,
        stage: Callable[[str], AbstractContextManager[object]] = lambda _name: nullcontext(),
    ) -> WriteOutcome:
        """Resume an existing plan or serialize one new model/plan invocation.

        恢复已有计划，或串行调用一次新模型并构造计划；默认不确认队列，原入口保持兼容。
        """
        rows = list(items or ())
        async with self._extract_lock:
            receipt = self._prepared.get(tuple(rows))
            if receipt is not None:
                return self._persist_plan(receipt, stage, log)
            if self._reserved(rows):
                return WriteOutcome(errors=("writeback_pending",), retryable=True)
            return await self._extract(
                rows, model, owner_id=owner_id, log=log, strict=strict,
                include_topic=include_topic, require_evidence=require_evidence,
                confirm_queue=confirm_queue, stage=stage,
            )

    async def _extract(
        self,
        items: Iterable[DialogueTurn] | None,
        model: ChatModel | LegacyTextModel | None,
        *,
        owner_id: str | None = None,
        log: Callable[[str], None] = lambda _msg: None,
        strict: bool = False,
        include_topic: bool = False,
        require_evidence: bool = False,
        confirm_queue: bool = False,
        stage: Callable[[str], AbstractContextManager[object]] = lambda _name: (
            nullcontext()
        ),
    ) -> WriteOutcome:
        """Call the model, build a validated plan, then persist it; failed input stays retryable / 调用模型并构造验证后的计划，再持久化，失败输入仍可重试。"""
        if (
            not items
            or self.artifacts is None
            or self.sources is None
            or model is None
        ):
            return WriteOutcome(errors=("invalid extraction input",))
        items = list(items)
        owner = self.owner_id() if owner_id is None else owner_id
        try:
            context = recover_parents(items, self.sources)
        except Exception as exc:
            if strict:
                raise
            log(f"parent recovery failed: {type(exc).__name__}")
            return WriteOutcome(errors=(f"parent: {exc}",), retryable=True)

        try:
            with stage("provider.call"):
                if hasattr(model, "complete"):
                    response = await model.complete(
                        ChatRequest(
                            session_id=str(items[0].session_id or ""),
                            system_prompt=build_prompt(
                                [], require_evidence=require_evidence
                            ),
                            prompt=dialogue_of(
                                context, include_topic=include_topic
                            ),
                        )
                    )
                    raw = getattr(response, "text", "") or ""
                else:
                    response = await model.text_chat(
                        system_prompt=build_prompt(
                            [], require_evidence=require_evidence
                        ),
                        prompt=dialogue_of(
                            context, include_topic=include_topic
                        ),
                    )
                    raw = getattr(response, "completion_text", "") or ""
            usage = self._response_usage(response)
            self._record_usage(usage)
        except Exception as exc:
            if strict:
                raise
            log(f"model call failed: {type(exc).__name__}")
            return WriteOutcome(
                errors=(f"model: {exc}",), model_failed=True, retryable=True
            )

        plan = build_plan(
            items,
            context,
            raw,
            self.cache,
            owner,
            log,
            strict=strict,
            require_evidence=require_evidence,
            stage=stage,
        )
        if plan.outcome is not None and (plan.outcome.model_failed or plan.outcome.retryable):
            return self._with_usage(plan.outcome, usage)
        receipt = PreparedExtraction(plan, tuple(items), confirm_queue)
        self._prepared[receipt.rows] = receipt
        return self._persist_plan(receipt, stage, log, usage=usage)

    def _persist_plan(
        self,
        receipt: PreparedExtraction,
        stage: Callable[[str], AbstractContextManager[object]],
        log: Callable[[str], None],
        *,
        usage: tuple[int, int, int] = (0, 0, 0),
    ) -> WriteOutcome:
        """Resume only unfinished writes; count new commits before fallible follow-up.

        仅恢复未完成写入，在可能失败的后续操作前记录新增提交数量。
        """
        plan = receipt.plan
        written_ids: list[str] = []
        errors = list(plan.errors)
        skipped = plan.outcome.skipped if plan.outcome is not None else plan.skipped
        for art in plan.artifacts:
            entity = art.header.id
            if entity not in receipt.committed:
                try:
                    with stage("artifact.persist"):
                        self.artifacts.commit(
                            art, expected_revision=0, op="create", reason="extract",
                            source_ids=tuple(art.header.lineage.sources),
                        )
                        # Record durability before diagnostics/cache can fail.
                        # 在诊断或缓存可能失败之前记录持久提交。
                        receipt.committed.add(entity)
                        written_ids.append(entity)
                        self._committed_total += 1
                except Exception as exc:
                    label = "diagnostic" if entity in receipt.committed else "commit"
                    errors.append(f"{label}: {type(exc).__name__}")
                    if entity not in receipt.committed:
                        continue
            if entity not in receipt.cached:
                try:
                    # Read the head on every retry; never publish the old prepared snapshot.
                    # 每次补偿读取当前版本，绝不发布旧的计划快照。
                    if self.cache is not None:
                        latest = self.artifacts.get(entity)
                        if latest is None:
                            self.cache.remove(entity)
                        else:
                            self.cache.put(latest)
                    receipt.cached.add(entity)
                except Exception as exc:
                    errors.append(f"cache: {type(exc).__name__}")
                    continue
            if entity not in receipt.enriched:
                # Enrichment is best effort, not a second durable-write owner.
                # 增强尽力执行，不成为第二个持久提交进度所有者。
                receipt.enriched.add(entity)
                try:
                    link_new(art, self.graph, self.cache)
                except Exception as exc:
                    errors.append(f"link: {type(exc).__name__}")
                try:
                    self._supersede(art)
                except Exception as exc:
                    errors.append(f"supersede: {type(exc).__name__}")
                try:
                    if self.cache is not None and str(art.payload.get("level") or "") == "impression":
                        with stage("impression.revise"):
                            revise_impression(self.artifacts, self.cache, art)
                except Exception as exc:
                    errors.append(f"impression: {type(exc).__name__}")
        complete = len(receipt.cached) == len(plan.artifacts)
        retryable = plan.retryable or not complete
        if complete and receipt.confirm_queue and not plan.retryable:
            try:
                self.buffer.mark_succeeded(list(receipt.rows))
            except Exception as exc:
                errors.append(f"queue: {type(exc).__name__}")
                complete = False
                retryable = True
        if complete:
            self._prepared.pop(receipt.rows, None)
        for error in errors[len(plan.errors):]:
            try:
                log(error)
            except Exception:
                pass  # Diagnostic failure cannot invalidate durable work / 诊断失败不能否定持久工作。
        return self._with_usage(WriteOutcome(
            written=len(written_ids), skipped=skipped, ids=tuple(written_ids),
            errors=tuple(errors), retryable=retryable,
        ), usage)

    def _reserved(self, rows: list[DialogueTurn]) -> bool:
        """Whether pending recovery owns any supplied input / 待补偿工作是否占用了任一给定输入。"""
        wanted = set(rows)
        source_ids = {row.source_id for row in rows if row.source_id}
        return any(
            wanted.intersection(receipt.rows)
            or source_ids.intersection(row.source_id for row in receipt.rows if row.source_id)
            for receipt in self._prepared.values()
        )

    def retry_writebacks(self) -> int:
        """Resume prepared writes without model calls; return completed operations.

        不调用模型，仅恢复已准备的写入；返回完成的操作数，补偿只在当前进程有效。
        """
        if self._retrying:
            return 0
        self._retrying = True
        completed = 0
        try:
            for receipt in tuple(self._prepared.values()):
                outcome = self._persist_plan(receipt, lambda _name: nullcontext(), lambda _msg: None)
                if not outcome.retryable:
                    completed += 1
        finally:
            self._retrying = False
        return completed

    def _supersede(self, new_art) -> int:
        """Expire matching superseded memories without deleting immutable Source / 终止匹配的旧记忆有效期，不删除不可变原始消息。"""
        payload = new_art.payload if isinstance(new_art.payload, dict) else {}
        old_text = str(payload.get("supersedes") or "").strip()
        if not old_text or self.cache is None:
            return 0
        key = re.sub(r"\s+", "", old_text).lower()
        cutoff = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        changed = 0
        for old in list(self.cache.active("memory")):
            if old.header.id == new_art.header.id:
                continue
            if old.header.subject_id != new_art.header.subject_id:
                continue
            if old.header.scope != new_art.header.scope:
                continue
            body = re.sub(r"\s+", "", content_of(old) or "").lower()
            if not key or not body or (key not in body and body not in key):
                continue
            updated = revise(old, time=replace(old.header.time, valid_to=cutoff))
            self.artifacts.commit(
                updated,
                expected_revision=old.header.revision,
                op="revise",
                reason="superseded by extraction",
                source_ids=tuple(old.header.lineage.sources),
            )
            self.cache.put(updated)
            changed += 1
        return changed
