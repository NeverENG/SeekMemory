"""Drive one scenario through a baseline using production capture, extraction, maintenance and recall.

用一个 baseline 把一个场景跑过生产捕获、抽取、维护及召回边界。

The harness never re-implements memory: it opens the production store, admits
turns through ``Buffer.add`` (the same admission path the host uses), runs
``IngestService.flush`` for extraction, ``MaintenanceService.weekly`` for
persona/relationship maintenance, ``ManagementService`` for persona rollback and
``RecallService`` for disclosed context.  Only the clock and the providers are
fake, which is exactly the boundary the issue allows.
"""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from core.domain.memory.graph import Graph
from core.domain.memory.source import Source, make_source_id
from perceive.buffer import Buffer
from services.ingest_service import IngestService
from services.maintenance_service import MaintenanceService
from services.management_service import ManagementService
from services.recall_service import RecallService
from store import open_store
from store.cache import Cache

from .adapter import ScriptedActor, ScriptedExtractor, ScriptedPersonaModel, UsageLedger, observe_emotion
from .clock import FakeClock
from .manifest import Checkpoint, Event, Manifest, Scenario

INJECTION_CHARS = 900
ROLLING_WINDOW = 24
WEEKLY_INTERVAL = 7


@dataclass(frozen=True)
class BaselineSpec:
    """Declare what one baseline does, so adding a baseline stays a data change.

    声明一个 baseline 做什么，使新增 baseline 只是数据改动。
    """

    id: str
    label: str
    captures: bool
    maintains: bool
    recalls: bool
    window: int = 0
    description: str = ""


SPECS: dict[str, BaselineSpec] = {
    "no-memory": BaselineSpec(
        "no-memory", "无记忆", False, False, False, 0,
        "只有固定人设，不捕获、不抽取、不召回；人格与关系都不演化。",
    ),
    "rolling-summary": BaselineSpec(
        "rolling-summary", "滚动摘要", False, False, False, ROLLING_WINDOW,
        "不持久化，只把最近若干轮对话拼进上下文；人格与关系都不演化。",
    ),
    "seekmemory-nomaint": BaselineSpec(
        "seekmemory-nomaint", "只记忆不维护", True, False, True, 0,
        "走真实捕获/抽取/召回，但跳过每周维护：没有人格合成、关系整固、衰退与合并。",
    ),
    "seekmemory": BaselineSpec(
        "seekmemory", "SeekMemory", True, True, True, 0,
        "完整生产路径：捕获、抽取、召回、每周维护与人格合成。",
    ),
}


class _Journal:
    """Minimal Journal port: record content-free counts, never payload text.

    最小 Journal 端口：只记录不含正文的计数。
    """

    def __init__(self) -> None:
        self.spans = 0
        self.records = 0

    def span(self, *_args, **_kwargs):
        """Yield a metric sink and count the closed span / 产出指标容器并统计结束的 span。"""
        from contextlib import contextmanager

        @contextmanager
        def _span():
            metrics: dict[str, Any] = {}
            yield metrics
            self.spans += 1

        return _span()

    def record(self, *_args, **_kwargs) -> None:
        """Count one diagnostic record without keeping its arguments / 统计一次诊断记录，不保留参数。"""
        self.records += 1


class _Logger:
    """Content-free logger: warnings are counted, never formatted with payload text.

    不含正文的日志器：只统计告警数量，不拼接正文。
    """

    def __init__(self) -> None:
        self.info_count = 0
        self.warning_count = 0

    def info(self, *_args, **_kwargs) -> None:
        self.info_count += 1

    def warning(self, *_args, **_kwargs) -> None:
        self.warning_count += 1


def _conf(**overrides):
    """Build the benchmark config: production keys only, no hidden behaviour switch.

    构造评测配置：只使用生产配置键，不引入隐藏行为开关。
    """
    values = {
        "recall_k": 8,
        "budget_chars": INJECTION_CHARS,
        "source_recall_enabled": False,
        "bm25_enabled": True,
        "persona_synthesis_enabled": True,
        "persona_synthesis_interval_days": WEEKLY_INTERVAL,
        "persona_synthesis_evidence_limit": 8,
        "persona_synthesis_evidence_chars": 2400,
        "relationship_mode": "observe",
        "max_sessions_per_flush": 6,
        "idle_flush_seconds": 0,
        "min_pending": 1,
        "max_flushes_per_day": 8,
        "backlog_flush_at": 30,
        "topic_ttl_seconds": 86400,
    }
    values.update(overrides)

    def conf(key: str, default: Any) -> Any:
        return values.get(key, default)

    return conf


class ScenarioRunner:
    """Run one scenario against one baseline and return content-free observations.

    对一个 baseline 运行一个场景，返回不含正文的观测结果。
    """

    def __init__(self, manifest: Manifest, scenario: Scenario, spec: BaselineSpec,
                 *, config: Mapping[str, Any] | None = None) -> None:
        self.manifest = manifest
        self.scenario = scenario
        self.spec = spec
        self.config = _conf(**(dict(config or {})))
        self.ledger = UsageLedger()
        self.privacy_markers = tuple(
            value for key, value in scenario.tokens.items() if key.startswith("privacy")
        )
        self.provider = ScriptedExtractor({}, self.ledger, forbidden=self.privacy_markers)
        self.persona_model = ScriptedPersonaModel(
            self.ledger, forbidden=self.privacy_markers, anchor="会记得对方说过的事"
        )
        self.actor = ScriptedActor(self.ledger)
        self.journal = _Journal()
        self.logger = _Logger()
        self.records: dict[str, tuple[dict[str, Any], ...]] = {}
        self.temp_dir = ""
        self.store = None
        self.cache = None
        self.graph = None
        self.buffer = None
        self.ingest = None
        self.maintenance = None
        self.management = None
        self.persona_id = ""
        self.recent: dict[str, list[str]] = {}
        self.checkpoints: list[dict[str, Any]] = []
        self.hard: dict[str, Any] = {
            "privacy_events": [],
            "persona_prompt_leaks": 0,
            "evidence_violations": 0,
            "baseline_stage": spec.id,
        }
        self.persona_history: list[dict[str, Any]] = []
        self.weekly_log: list[dict[str, Any]] = []
        self.restarts = 0
        self.rollback_events: list[dict[str, Any]] = []

    # ------------------------------------------------------------------ #
    # Store and service wiring
    # ------------------------------------------------------------------ #

    def _open(self) -> None:
        """Create the isolated store and bind every production service / 创建隔离存储并接线全部生产服务。"""
        self.temp_dir = tempfile.mkdtemp(prefix="seekmemory_lh_")
        self.store = open_store(str(Path(self.temp_dir) / "memory.db"))
        self.cache = Cache(self.store.artifacts)
        self.graph = Graph(self.store.artifacts)
        self.buffer = Buffer("", extraction=self.store.extraction)
        self._bind()

    def _bind(self) -> None:
        """Rebind services to the current store/cache after a restart / 重启后把服务接到当前存储与缓存。"""
        assert self.store is not None and self.cache is not None and self.buffer is not None
        self.provider.records = self.records
        self.ingest = IngestService(
            buffer=self.buffer,
            artifacts=self.store.artifacts,
            sources=self.store.sources,
            extraction=self.store.extraction,
            cache=self.cache,
            graph=self.graph,
            journal=self.journal,
            config=self.config,
            provider_for=self._provider_for,
            owner_id=lambda: str(self.manifest.owner["id"]),
            logger=self.logger,
        )
        self.maintenance = MaintenanceService(
            artifacts=self.store.artifacts,
            sources=self.store.sources,
            cache=self.cache,
            journal=self.journal,
            task_id=lambda: "long-horizon",
            logger=self.logger,
            config=self.config,
            persona_model=self._persona_for,
            clock=lambda: self.clock.now,
        )
        self.management = ManagementService(
            self.store.artifacts, self.store.sources, self.store.ledger, self.cache, None
        )

    async def _provider_for(self, _session_id):
        """Return the same frozen provider for every session / 每个会话返回同一个冻结提供方。"""
        return self.provider

    async def _persona_for(self):
        """Return the deterministic persona writer / 返回确定性人格撰写器。"""
        return self.persona_model

    def _restart(self) -> None:
        """Close and reopen the store, then rebind services and reload the cache.

        关闭并重新打开存储，重新接线并重载缓存；与宿主重启路径一致。
        """
        assert self.store is not None
        path = str(Path(self.temp_dir) / "memory.db")
        self.store.close()
        self.store = open_store(path)
        self.cache = Cache(self.store.artifacts)
        self.cache.load()
        self.graph = Graph(self.store.artifacts)
        self.buffer = Buffer("", extraction=self.store.extraction)
        self._bind()

    # ------------------------------------------------------------------ #
    # Capture
    # ------------------------------------------------------------------ #

    def _capture(self, event: Event) -> None:
        """Admit one authored event through the production capture path.

        通过生产捕获路径接纳一个事件；不捕获的 baseline 只更新滚动窗口。
        """
        session = self.manifest.sessions[event.session]
        owner = str(self.manifest.owner["id"])
        prepared: list[tuple[str, Source]] = []
        for index, turn in enumerate(event.turns):
            at = self.clock.now.replace(hour=9, minute=index).isoformat(timespec="seconds")
            speaker = owner if turn.role == "user" else "bot"
            source_id = make_source_id(
                session_id=session, speaker_id=speaker, role=turn.role, text=turn.text, at=at
            )
            reply_to = prepared[-1][0] if turn.role == "assistant" and prepared else None
            prepared.append((source_id, Source(
                source_id, f"{self.scenario.id}:{event.day}:{index}", session, speaker,
                turn.role, turn.text, at, reply_to,
            )))
        ids = [source_id for source_id, _source in prepared]
        for index, (source_id, source) in enumerate(prepared):
            turn = event.turns[index]
            items: list[dict[str, Any]] = []
            for item in turn.extract:
                payload = {key: value for key, value in item.items() if key != "evidence"}
                payload["evidence_source_ids"] = [ids[position] for position in item["evidence"]]
                payload.setdefault("confidence", 0.95)
                payload.setdefault("event_at", source.at)
                payload["owner_umo"] = session
                items.append(payload)
            if items:
                self.records[source_id] = tuple(items)
            self.recent.setdefault(session, []).append(f"{turn.role}: {turn.text}")
            if not self.spec.captures:
                continue
            assert self.store is not None and self.buffer is not None
            source.validate()
            self.store.sources.append_sources([source])
            self.buffer.add(
                session,
                turn.text,
                source.speaker_id,
                source_id=source.id,
                at=source.at,
                source=source,
                turn_id=source.turn_id,
                reply_to=source.reply_to or "",
                role=turn.role,
            )

    def _flush(self) -> None:
        """Run the production extraction entry point for the pending buffer / 对待处理缓冲运行生产抽取入口。"""
        assert self.ingest is not None
        asyncio.run(self.ingest.flush("long-horizon", batch_cap=6))

    # ------------------------------------------------------------------ #
    # Baseline-specific context and state
    # ------------------------------------------------------------------ #

    def _recall(self, probe: str, *, session: str | None = None, speaker: str | None = None) -> tuple[str, dict]:
        """Read disclosed context through RecallService without writing / 通过 RecallService 只读读取披露上下文。"""
        assert self.store is not None and self.cache is not None
        service = RecallService(
            cache=self.cache,
            graph=self.graph,
            artifacts=self.store.artifacts,
            sources=self.store.sources,
            budget=_Budget(),
            config=self.config,
            owner_umo=lambda: str(self.manifest.owner["umo"]),
        )
        return service.build(
            probe,
            session or self.manifest.sessions["owner"],
            private=True,
            speaker=speaker or str(self.manifest.owner["id"]),
            dry_run=True,
        )

    def _context(self, probe: str, *, session_key: str = "owner") -> tuple[str, dict[str, Any]]:
        """Return the baseline's context and content-free shape information / 返回上下文及无正文的形态信息。"""
        session = self.manifest.sessions[session_key]
        if self.spec.recalls:
            block, info = self._recall(
                probe,
                session=session,
                speaker=str(self.manifest.owner["id"]) if session_key == "owner"
                else str(self.manifest.owner["stranger_umo"]).split(":")[-1],
            )
            return block, {
                "chars": len(block),
                "items": len(info.get("final_ids") or ()),
                "mode": str(info.get("mode") or "none"),
            }
        if self.spec.window:
            turns = self.recent.get(session, [])
            text = "\n".join(turns[-self.spec.window:])[-INJECTION_CHARS:]
            return text, {"chars": len(text), "items": min(len(turns), self.spec.window), "mode": "window"}
        return "", {"chars": 0, "items": 0, "mode": "none"}

    def _persona_state(self) -> tuple[str, int, str]:
        """Read the visible persona text, revision and origin / 读取可见人格文本、版本与来源。"""
        if not self.spec.captures or self.cache is None:
            return str(self.scenario.role["persona"]), 1, "seed"
        active = self.cache.active("persona")
        if not active:
            return str(self.scenario.role["persona"]), 1, "seed"
        art = active[-1]
        return str(art.payload.get("text") or ""), int(art.header.revision), str(art.payload.get("origin") or "seed")

    def _band(self) -> str | None:
        """Read the consolidated relationship band, or None when absent / 读取关系档位，不存在时返回空。"""
        if not self.spec.maintains or self.cache is None:
            return None
        active = self.cache.active("relationship")
        if not active:
            return None
        return str(active[-1].payload.get("relation_band") or "") or None

    def _memory_state(self) -> dict[str, Any]:
        """Summarize memory counts and evidence integrity without reading text into the report.

        汇总记忆计数与证据完整性；不把正文写进报告。
        """
        if not self.spec.captures or self.cache is None or self.store is None:
            return {"active": 0, "expired": 0, "with_sources": 0, "broken_sources": 0}
        active = self.cache.active("memory")
        expired = sum(1 for art in active if art.header.time.valid_to)
        source_ids = {sid for art in active for sid in art.header.lineage.sources}
        known = self.store.sources.sources_by_ids(sorted(source_ids)) if source_ids else {}
        with_sources = sum(1 for art in active if art.header.lineage.sources)
        broken = sum(1 for art in active for sid in art.header.lineage.sources if sid not in known)
        return {
            "active": len(active),
            "expired": expired,
            "with_sources": with_sources,
            "broken_sources": broken,
        }

    def _stale_state(self, checkpoint: Checkpoint) -> dict[str, Any]:
        """Check whether a superseded fact is still live in the owner's context.

        检查被更正的事实是否仍留在主人的上下文里。
        """
        if not checkpoint.forbid_tokens or not self.spec.captures or self.cache is None:
            return {"applicable": False, "stale_live": 0, "stale_expired": 0}
        stale = [
            art for art in self.cache.active("memory")
            if any(token in str(art.payload.get("text") or "") for token in checkpoint.forbid_tokens)
        ]
        return {
            "applicable": True,
            "stale_live": sum(1 for art in stale if not art.header.time.valid_to),
            "stale_expired": sum(1 for art in stale if art.header.time.valid_to),
        }

    # ------------------------------------------------------------------ #
    # Checkpoints
    # ------------------------------------------------------------------ #

    def _checkpoint(self, checkpoint: Checkpoint) -> None:
        """Produce one visible performance and record only content-free facts.

        产生一次可见表演，只记录不含正文的事实。
        """
        context, shape = self._context(checkpoint.probe)
        persona_text, revision, origin = self._persona_state()
        band = self._band()
        performance = self.actor.perform(
            probe=checkpoint.probe,
            context=context,
            persona_text=persona_text,
            tokens=self.scenario.tokens,
            cues=self.scenario.cues,
            actions=self.scenario.actions,
            band=band or "neutral",
            persona_evolved=revision > 1,
        )
        observed = observe_emotion(performance.text, self.scenario.cues)
        stranger_block, _shape = self._context(checkpoint.probe, session_key="stranger")
        # A private fact may appear in the owner's own answer; it must never reach
        # another session's context or the shared persona.
        # 私人事实可以出现在主人自己的回复里，但绝不能进入别人会话的上下文或共享人格。
        stranger_leaks = [marker for marker in self.privacy_markers if marker in stranger_block]
        persona_leaks = [marker for marker in self.privacy_markers if marker in persona_text]
        for _marker in stranger_leaks:
            self.hard["privacy_events"].append({"checkpoint": checkpoint.day, "where": "stranger_context"})
        for _marker in persona_leaks:
            self.hard["privacy_events"].append({"checkpoint": checkpoint.day, "where": "persona"})
        memory = self._memory_state()
        stale = self._stale_state(checkpoint)
        self.hard["evidence_violations"] += int(memory["broken_sources"])
        expected_hits = sum(1 for token in checkpoint.expect_tokens if token in performance.text)
        forbidden_hits = sum(1 for token in checkpoint.forbid_tokens if token in performance.text)
        context_forbidden = sum(1 for token in checkpoint.forbid_tokens if token in context)
        steered = self._correction(performance, checkpoint, context, persona_text, band, revision)
        self.checkpoints.append({
            "day": checkpoint.day,
            "context": shape,
            "context_sha": hashlib.sha256(context.encode("utf-8")).hexdigest()[:16],
            "response_sha": hashlib.sha256(performance.text.encode("utf-8")).hexdigest()[:16],
            "response_chars": len(performance.text),
            "actions": list(performance.actions),
            "memory_hits": list(performance.memory_hits),
            "observed_emotion": observed,
            "intended_intensity": {key: round(value, 2) for key, value in performance.intensities.items()},
            "cue_bands": dict(performance.cue_bands),
            "expected_total": len(checkpoint.expect_tokens),
            "expected_hits": expected_hits,
            "forbidden_total": len(checkpoint.forbid_tokens),
            "forbidden_hits": forbidden_hits,
            "context_forbidden_hits": context_forbidden,
            "band": band,
            "persona": {"revision": revision, "origin": origin},
            "memory": memory,
            "stale": stale,
            "privacy": {"stranger_hits": len(stranger_leaks), "persona_hits": len(persona_leaks)},
            "steered": steered,
        })
        self.persona_history.append({"day": checkpoint.day, "revision": revision, "origin": origin})

    def _correction(self, performance, checkpoint: Checkpoint, context: str,
                    persona_text: str, band: str | None, revision: int) -> dict[str, Any]:
        """Run one optional one-take correction from the same checkpoint snapshot.

        只对预先声明的检查点，从同一份上下文与人格快照复跑一次；它不得修改证据、
        不得重新抽取，也不得进入自然成绩。
        """
        if not checkpoint.correction:
            return {"attempted": False}
        before = self.ledger.stage("correction").total_tokens
        steered = self.actor.perform(
            probe=checkpoint.probe,
            context=context,
            persona_text=persona_text,
            tokens=self.scenario.tokens,
            cues=self.scenario.cues,
            actions=self.scenario.actions,
            band=band or "neutral",
            persona_evolved=revision > 1,
            correction=True,
        )
        after = self.ledger.stage("correction").total_tokens
        natural_ok = (
            all(token in performance.text for token in checkpoint.expect_tokens)
            and set(checkpoint.expect_actions) <= set(performance.actions)
        )
        steered_ok = (
            all(token in steered.text for token in checkpoint.expect_tokens)
            and set(checkpoint.expect_actions) <= set(steered.actions)
        )
        steered_forbidden = sum(1 for token in checkpoint.forbid_tokens if token in steered.text)
        privacy_hits = sum(1 for marker in self.privacy_markers if marker in steered.text)
        overcorrected = bool(
            steered_forbidden
            or privacy_hits
            or (len(steered.text) > 2 * len(performance.text) + 20)
        )
        if privacy_hits:
            self.hard["privacy_events"].append({"checkpoint": checkpoint.day, "where": "steered_response"})
        return {
            "attempted": True,
            "natural_compliant": natural_ok,
            "recovered": bool(steered_ok and not natural_ok),
            "steered_compliant": steered_ok,
            "withheld_naturally": bool(performance.withheld),
            "overcorrected": overcorrected,
            "privacy_hits": privacy_hits,
            "extra_calls": 1,
            "extra_tokens": max(0, after - before),
        }

    # ------------------------------------------------------------------ #
    # Run
    # ------------------------------------------------------------------ #

    def run(self) -> dict[str, Any]:
        """Execute one scenario/baseline pair and return its observations / 执行一组场景与 baseline 并返回观测。"""
        started = time.perf_counter()
        self.clock = FakeClock(self.manifest.start)
        try:
            with self.clock.frozen():
                if self.spec.captures:
                    self._open()
                    assert self.management is not None
                    self.persona_id = str(self.management.bootstrap_persona(dict(self.scenario.role))["id"])
                by_day: dict[int, list[Event]] = {}
                for event in self.scenario.events:
                    by_day.setdefault(event.day, []).append(event)
                for event in self.scenario.milestones:
                    by_day.setdefault(event.day, []).append(event)
                order = {"dialogue": 0, "restart": 1, "rollback": 2}
                for items in by_day.values():
                    items.sort(key=lambda item: order.get(item.kind, 3))
                checkpoints = {checkpoint.day: checkpoint for checkpoint in self.scenario.checkpoints}
                current = self.manifest.start
                last_weekly = 0
                for day in range(1, max(self.manifest.horizons) + 1):
                    target = self.manifest.start + _days(day)
                    self.clock.advance(days=(target - current).days)
                    current = target
                    for event in by_day.get(day, ()):
                        if event.kind == "dialogue":
                            self._capture(event)
                            if self.spec.captures:
                                self._flush()
                        elif event.kind == "restart":
                            if self.spec.captures:
                                self._restart()
                                self.restarts += 1
                        elif event.kind == "rollback":
                            if self.spec.captures and self.spec.maintains:
                                assert self.management is not None
                                before = self._persona_state()
                                try:
                                    self.management.rollback_persona({
                                        "id": self.persona_id,
                                        "revision": int(event.revision or 1),
                                        "reason": event.reason,
                                        "confirmed": True,
                                    })
                                    after = self._persona_state()
                                    self.rollback_events.append({
                                        "day": day,
                                        "before_revision": before[1],
                                        "after_revision": after[1],
                                        "after_origin": after[2],
                                        "skipped": False,
                                    })
                                except ValueError:
                                    # No evolved revision to roll back to: report, never hide.
                                    # 没有可回滚的演化版本：如实记录，不掩盖。
                                    self.rollback_events.append({
                                        "day": day,
                                        "before_revision": before[1],
                                        "after_revision": before[1],
                                        "after_origin": before[2],
                                        "skipped": True,
                                    })
                    if self.spec.maintains and day % WEEKLY_INTERVAL == 0 and day != last_weekly:
                        assert self.maintenance is not None
                        weekly = asyncio.run(self.maintenance.weekly())
                        self.weekly_log.append({
                            "day": day,
                            "relationships": int(weekly.get("relationships") or 0),
                            "self_impressions": int(weekly.get("self_impressions") or 0),
                            "forgotten": int(weekly.get("forgotten") or 0),
                            "merged": int(weekly.get("merged") or 0),
                            "persona_status": str((weekly.get("persona_result") or {}).get("status") or ""),
                        })
                        last_weekly = day
                    if day in checkpoints:
                        self._checkpoint(checkpoints[day])
                memory_final = self._memory_state()
        finally:
            if self.store is not None:
                try:
                    self.store.close()
                except Exception:  # noqa: BLE001 - closing twice must not hide results
                    pass
            if self.temp_dir:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
        self.hard["persona_prompt_leaks"] = int(self.persona_model.prompt_leaks)
        if self.persona_model.prompt_leaks:
            self.hard["privacy_events"].append({"checkpoint": 0, "where": "persona_prompt"})
        usage = self.ledger.as_dict()
        if not self.spec.captures:
            self.ledger.unavailable("extraction")
            self.ledger.unavailable("persona")
            usage = self.ledger.as_dict()
        return {
            "scenario": self.scenario.id,
            "baseline": self.spec.id,
            "label": self.spec.label,
            "checkpoints": self.checkpoints,
            "usage": usage,
            "hard": self.hard,
            "persona_history": self.persona_history,
            "restarts": self.restarts,
            "weekly": self.weekly_log,
            "rollbacks": self.rollback_events,
            "memory_final": memory_final,
            "journal": {"spans": self.journal.spans, "records": self.journal.records},
            "logger": {"info": self.logger.info_count, "warning": self.logger.warning_count},
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }


class _Budget:
    """Minimal budget object shaped like ``app.budget.ContextBudget`` / 与 ContextBudget 同形的最小预算对象。"""

    injection_chars = INJECTION_CHARS
    system_chars = 1600


def _days(value: int):
    """Return a day offset without importing datetime at call sites / 返回天数偏移。"""
    import datetime

    return datetime.timedelta(days=value)


def run_baseline(manifest: Manifest, scenario: Scenario, baseline: str,
                 *, config: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Run one baseline by id and return its observations / 按编号运行一个 baseline 并返回观测。"""
    try:
        spec = SPECS[baseline]
    except KeyError:
        raise ValueError(f"unknown baseline {baseline!r}; choose from {sorted(SPECS)}") from None
    return ScenarioRunner(manifest, scenario, spec, config=config).run()


__all__ = ["BaselineSpec", "SPECS", "ScenarioRunner", "run_baseline"]

