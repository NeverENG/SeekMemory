#!/usr/bin/env python3
"""Deterministic Dream triage / cost tradeoff evaluation harness.

The harness runs the real ``DreamCycle -> IngestService.flush`` path against an
isolated in-memory SQLite store and a frozen synthetic corpus. The only fake is
the model provider: it returns pre-recorded extraction items keyed by the
Source ids that the production prompt renders. No network, no real chat text,
and no second Artifact write path are involved.

Usage::

    python benchmarks/dream_eval.py --repo . --label current \
        --output benchmarks/results/dream_tradeoff_current.json

The JSON report contains counts, labels and topic ids only. Turn text and
recorded extraction text never appear in the report.

Run ``python benchmarks/dream_tradeoff.py`` to execute several checkouts and
render the before/after Markdown report.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import datetime
import hashlib
import importlib
import inspect
import json
import platform
import re
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
DEFAULT_CORPUS = HERE / "data" / "dream_tradeoff_corpus.jsonl"
SCHEMA = "seekmemory.dream_tradeoff.v1"
FIXED_NOW = "2026-10-20T03:31:00"
OWNER_ID = "10001"
SELF_IMPRESSION_MIN_EVIDENCE = 3

CHARS_PER_TOKEN = 1.6
MESSAGE_OVERHEAD = 4
PROMPT_MESSAGES = 2
OUTPUT_MESSAGES = 1

THRESHOLDS: dict[str, float] = {
    "min_important_fact_recall": 0.85,
    "min_behavior_coverage": 0.85,
    "min_self_impression_coverage": 0.85,
    "max_false_memory_rate": 0.10,
    "max_duplicate_rate": 0.02,
    "min_call_reduction": 0.50,
    "min_token_reduction": 0.50,
    "max_pending_ratio": 0.50,
}

_SOURCE_ID = re.compile(r"\[(s_[A-Za-z0-9_]+)\]")
_TEXT_FIELDS = (
    "level",
    "text",
    "tags",
    "about",
    "subject_kind",
    "subject_id",
    "subject_name",
    "event_at",
    "valid_from",
    "valid_to",
    "supersedes",
    "confidence",
    "arousal",
    "valence",
    "funny",
    "first",
    "bot_behavior",
    "bot_action",
    "bot_tone",
    "bot_boundary",
    "outcome",
)


# --------------------------------------------------------------------------- #
# Corpus and generic helpers
# --------------------------------------------------------------------------- #


def normalize(text: str) -> str:
    """Normalize text for literal matching; mirrors extraction dedupe."""
    return re.sub(r"[\s\W_]+", "", str(text or "")).lower()


def estimate_tokens(chars: int, messages: int = 0) -> int:
    """Same deterministic estimate used by ``app.budget``; no provider call."""
    body = int(max(0, int(chars)) / CHARS_PER_TOKEN)
    return body + MESSAGE_OVERHEAD * max(0, int(messages))


def load_corpus(path: Path | str) -> list[dict[str, Any]]:
    """Load and validate the frozen JSONL corpus."""
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict):
            raise ValueError(f"corpus line {line_no} is not an object")
        rows.append(row)
    validate_corpus(rows)
    return rows


def validate_corpus(rows: Iterable[dict[str, Any]]) -> None:
    """Check the frozen labels the harness relies on."""
    rows = list(rows)
    ids = [str(row.get("id") or "") for row in rows]
    if len(rows) < 30:
        raise ValueError(f"corpus needs at least 30 topics, got {len(rows)}")
    if len(ids) != len(set(ids)) or not all(ids):
        raise ValueError("corpus topic ids must be unique and non-empty")
    classes = {str(row.get("class") or "") for row in rows}
    missing = {"fact", "behavior", "chatter", "backlog"} - classes
    if missing:
        raise ValueError(f"corpus missing classes: {sorted(missing)}")
    for row in rows:
        tid = str(row["id"])
        turns = row.get("turns") or []
        if not turns or turns[0].get("role") != "user":
            raise ValueError(f"{tid}: first turn must be a user turn")
        if not row.get("synthetic"):
            raise ValueError(f"{tid}: corpus must be marked synthetic")
        for item in row.get("recorded") or []:
            evidence = list(item.get("evidence") or [])
            if not evidence or any(
                not isinstance(index, int) or index < 0 or index >= len(turns)
                for index in evidence
            ):
                raise ValueError(f"{tid}: invalid evidence indices")
            if item.get("bot_behavior"):
                if evidence != [0, 1]:
                    raise ValueError(f"{tid}: behavior evidence must be one pair")
                if turns[1].get("reply_to") != 0:
                    raise ValueError(f"{tid}: behavior reply must reference its user")
        if row["class"] == "behavior" and not (
            row.get("recorded") and row["recorded"][0].get("bot_behavior")
        ):
            raise ValueError(f"{tid}: behavior topic needs a recorded behavior")
        if row["class"] != "behavior" and any(
            item.get("bot_behavior") for item in row.get("recorded") or []
        ):
            raise ValueError(f"{tid}: non-behavior topic carries bot_behavior")


def corpus_snapshot(path: Path | str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Content-free corpus description used by JSON and Markdown reports."""
    raw = Path(path).read_bytes()
    sessions = Counter(str(row["session"]) for row in rows)
    behaviors = Counter(
        str(row["truth"]["behavior"])
        for row in rows
        if row.get("truth", {}).get("kind") == "behavior"
    )
    return {
        "sha256": hashlib.sha256(raw).hexdigest(),
        "topics": len(rows),
        "classes": dict(sorted(Counter(str(row["class"]) for row in rows).items())),
        "important_topics": sum(1 for row in rows if row.get("important")),
        "synthetic": True,
        "sessions": dict(sorted(sessions.items())),
        "behavior_episodes": dict(sorted(behaviors.items())),
        "fixed_clock": FIXED_NOW,
    }


def harness_digest() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


# --------------------------------------------------------------------------- #
# Target checkout loading and feature detection
# --------------------------------------------------------------------------- #


class TargetModules:
    """Import production modules from one checkout without mixing revisions."""

    def __init__(self, repo: Path | str) -> None:
        self.repo = Path(repo).resolve()
        if not (self.repo / "services" / "ingest_service.py").exists():
            raise FileNotFoundError(f"not a SeekMemory checkout: {self.repo}")
        sys.path.insert(0, str(self.repo))
        self.contracts = self._import("app.contracts")
        self.dream = self._import("app.dream")
        self.buffer = self._import("perceive.buffer")
        self.ingest = self._import("services.ingest_service")
        self.cache_module = self._import("store.cache")
        self.graph_module = self._import("core.domain.memory.graph")
        self.source_module = self._import("core.domain.memory.source")
        self.bot_behavior = self._import("core.bot_behavior")
        self.store_module = self._import("store")
        self.self_impression = self._import("maintain.self_impression")
        try:
            self.importance = self._import("perceive.importance")
        except ImportError:
            self.importance = None
        self._assert_from_repo()

    def _import(self, name: str):
        module = importlib.import_module(name)
        self._cleanup_previous(name, module)
        return module

    def _cleanup_previous(self, name: str, module) -> None:
        """Refuse to silently evaluate a module from a different checkout."""
        current = Path(str(getattr(module, "__file__", ""))).resolve()
        repo = self.repo
        try:
            current.relative_to(repo)
        except ValueError:
            raise RuntimeError(
                f"{name} resolved outside {repo}: {current}. Run one target per "
                "process (benchmarks/dream_tradeoff.py does this)."
            ) from None

    def _assert_from_repo(self) -> None:
        modules = {
            "app.dream": self.dream,
            "services.ingest_service": self.ingest,
            "perceive.buffer": self.buffer,
            "store": self.store_module,
        }
        for name, module in modules.items():
            self._cleanup_previous(name, module)

    @property
    def supports_triage(self) -> bool:
        return "triage" in inspect.signature(self.ingest.IngestService.flush).parameters

    @property
    def supports_budget_kwargs(self) -> bool:
        params = inspect.signature(self.ingest.IngestService.flush).parameters
        return "max_calls" in params and "max_tokens" in params

    @property
    def supports_usage(self) -> bool:
        return "usage" in inspect.signature(self.dream.DreamCycle.run).parameters

    @property
    def has_importance(self) -> bool:
        return self.importance is not None

    def feature_paths(self) -> dict[str, bool]:
        return {
            "dream_cycle": True,
            "ingest_service_flush": True,
            "triage_parameter": self.supports_triage,
            "call_budget_parameter": self.supports_budget_kwargs,
            "token_budget_parameter": self.supports_budget_kwargs,
            "usage_snapshot": hasattr(self.ingest.IngestService, "usage_snapshot"),
            "usage_callback": self.supports_usage,
            "importance_module": self.has_importance,
            "self_impression_maintenance": True,
        }


# --------------------------------------------------------------------------- #
# Fake provider and eval-side plumbing
# --------------------------------------------------------------------------- #


class RecordedProvider:
    """Deterministic provider returning frozen extraction items by Source id.

    Usage is estimated from the actual prompt and output length with the same
    formula as ``app.budget``. It is not provider-reported; the report states
    that limitation. ``usage_cached`` stays zero because no prefix cache is
    simulated.
    """

    name = "deterministic-recorded"

    def __init__(
        self,
        topic_records: dict[str, list[dict[str, Any]]],
        source_to_topic: dict[str, str],
        topic_priority: dict[str, int],
    ) -> None:
        self.topic_records = topic_records
        self.source_to_topic = source_to_topic
        self.topic_priority = topic_priority
        self.calls = 0
        self.usage_in = 0
        self.usage_cached = 0
        self.usage_out = 0
        self.prompt_chars = 0
        self.output_chars = 0
        self.calls_with_multiple_topics = 0
        self.max_topics_per_call = 0
        self.calls_with_overflow = 0
        self.call_log: list[dict[str, int]] = []

    def meta(self):
        return SimpleNamespace(id="seekmemory-eval-fake", model=self.name)

    async def text_chat(self, system_prompt: str = "", prompt: str = ""):
        self.calls += 1
        topic_ids: list[str] = []
        for source_id in _SOURCE_ID.findall(prompt):
            topic_id = self.source_to_topic.get(source_id)
            if topic_id and topic_id not in topic_ids:
                topic_ids.append(topic_id)
        entries: list[tuple[int, dict[str, Any]]] = []
        for topic_id in topic_ids:
            priority = self.topic_priority.get(topic_id, 2)
            for item in self.topic_records.get(topic_id, []):
                entries.append((priority, dict(item)))
        entries.sort(key=lambda pair: pair[0])
        items = [item for _priority, item in entries]
        text = json.dumps(items, ensure_ascii=False)
        usage_in = estimate_tokens(
            len(system_prompt) + len(prompt), PROMPT_MESSAGES
        )
        usage_out = estimate_tokens(len(text), OUTPUT_MESSAGES)
        self.usage_in += usage_in
        self.usage_out += usage_out
        self.prompt_chars += len(prompt)
        self.output_chars += len(text)
        if len(topic_ids) > 1:
            self.calls_with_multiple_topics += 1
        self.max_topics_per_call = max(self.max_topics_per_call, len(topic_ids))
        if len(items) > 6:
            self.calls_with_overflow += 1
        self.call_log.append(
            {
                "topics": len(topic_ids),
                "sources": len(set(_SOURCE_ID.findall(prompt))),
                "items": len(items),
                "prompt_chars": len(prompt),
            }
        )
        usage = SimpleNamespace(input=usage_in, input_cached=0, output=usage_out)
        return SimpleNamespace(
            completion_text=text, usage=usage, id=f"eval-{self.calls}"
        )


class EvalJournal:
    """Minimal Journal port; records only metrics, never message text."""

    def __init__(self) -> None:
        self.rows: list[tuple[Any, ...]] = []

    @contextlib.contextmanager
    def span(self, *args, **kwargs):
        metrics: dict[str, Any] = {}
        yield metrics
        self.rows.append(("span", args, kwargs, dict(metrics)))

    def record(self, *args, **kwargs) -> None:
        self.rows.append(("record", args, kwargs))


class EvalLogger:
    """Collect warning counts only; logs are content-free."""

    def __init__(self) -> None:
        self.info_count = 0
        self.warning_count = 0

    def info(self, *_args, **_kwargs) -> None:
        self.info_count += 1

    def warning(self, *_args, **_kwargs) -> None:
        self.warning_count += 1


# --------------------------------------------------------------------------- #
# Seeding and production-path execution
# --------------------------------------------------------------------------- #


def _parse_time(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(str(value))


def _conf_factory() -> Any:
    overrides = {
        "dream_enabled": True,
        "dream_time": "03:30",
        "dream_max_batches": 100,
        "dream_max_calls": 100,
        "dream_token_budget": 1_000_000,
        "dream_batch_tokens": 6000,
        "max_sessions_per_flush": 6,
        "idle_flush_seconds": 0,
        "min_pending": 8,
        "max_flushes_per_day": 2,
        "backlog_flush_at": 30,
        "topic_ttl_seconds": 86400,
    }

    def conf(key: str, default: Any) -> Any:
        return overrides.get(key, default)

    return conf


def seed_corpus(
    modules: TargetModules,
    store,
    topics: Iterable[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, list[str]], dict[str, list[dict[str, Any]]]]:
    """Append Sources and extraction rows through the production repository.

    This is the same admission path ``Buffer.add`` uses. No Artifact is built
    or committed here; extraction remains owned by ``IngestService``.
    """
    source_to_topic: dict[str, str] = {}
    topic_sources: dict[str, list[str]] = {}
    topic_records: dict[str, list[dict[str, Any]]] = {}
    for topic in topics:
        tid = str(topic["id"])
        start = _parse_time(topic["at"])
        sources: list[str] = []
        for index, turn in enumerate(topic["turns"]):
            at = (start + datetime.timedelta(seconds=10 * index)).isoformat(
                timespec="seconds"
            )
            role = str(turn["role"])
            speaker = str(topic["speaker"]) if role == "user" else "bot"
            reply_to = None
            if turn.get("reply_to") is not None:
                reply_to = sources[int(turn["reply_to"])]
            source_id = modules.source_module.make_source_id(
                session_id=str(topic["session"]),
                speaker_id=speaker,
                role=role,
                text=str(turn["text"]),
                at=at,
            )
            source = modules.source_module.Source(
                source_id,
                f"{tid}:{index}",
                str(topic["session"]),
                speaker,
                role,
                str(turn["text"]),
                at,
                reply_to,
            )
            store.extraction.enqueue_extraction(source, tid, at)
            sources.append(source_id)
            source_to_topic[source_id] = tid
        topic_sources[tid] = sources
        records: list[dict[str, Any]] = []
        for recorded in topic.get("recorded") or []:
            item = {key: recorded[key] for key in _TEXT_FIELDS if key in recorded}
            item["evidence_source_ids"] = [
                sources[int(index)] for index in recorded["evidence"]
            ]
            records.append(item)
        topic_records[tid] = records
    return source_to_topic, topic_sources, topic_records


def _triage_snapshot(modules: TargetModules, buffer) -> tuple[set[str] | None, dict[str, Any]]:
    if not modules.has_importance:
        return None, {"applied": False, "scores": {}}
    ranked = modules.importance.rank_topics(buffer.items)
    threshold = float(modules.importance.MIN_IMPORTANCE_SCORE)
    eligible = {
        str(item.topic_id)
        for item in ranked
        if float(item.score) >= threshold
    }
    scores = {
        str(item.topic_id): {
            "score": round(float(item.score), 2),
            "reasons": list(item.reasons),
        }
        for item in ranked
    }
    return eligible, {
        "applied": True,
        "threshold": threshold,
        "scores": scores,
    }


def _drive(
    modules: TargetModules,
    topics: list[dict[str, Any]],
    now: datetime.datetime,
    maintenance: bool,
) -> dict[str, Any]:
    """Run one Dream cycle on one isolated store and return content-free metrics."""
    store = modules.store_module.open_store(":memory:")
    try:
        source_to_topic, _topic_sources, topic_records = seed_corpus(
            modules, store, topics
        )
        buffer = modules.buffer.Buffer("", extraction=store.extraction)
        cache = modules.cache_module.Cache(store.artifacts)
        graph = modules.graph_module.Graph(store.artifacts)
        journal = EvalJournal()
        logger = EvalLogger()
        priority = {
            str(topic["id"]): (
                0
                if str(topic.get("truth", {}).get("kind")) == "behavior"
                else 1
                if str(topic.get("truth", {}).get("kind")) == "fact"
                else 2
            )
            for topic in topics
        }
        provider = RecordedProvider(topic_records, source_to_topic, priority)
        config = _conf_factory()

        async def provider_for(_session_id):
            return provider

        service = modules.ingest.IngestService(
            buffer=buffer,
            artifacts=store.artifacts,
            sources=store.sources,
            extraction=store.extraction,
            cache=cache,
            graph=graph,
            journal=journal,
            config=config,
            provider_for=provider_for,
            owner_id=lambda: OWNER_ID,
            logger=logger,
        )
        flush_params = inspect.signature(service.flush).parameters

        async def flush_once(reason: str, **kwargs):
            accepted = {key: value for key, value in kwargs.items() if key in flush_params}
            return await service.flush(reason, **accepted)

        async def maintain():
            made = modules.self_impression.build_self_impressions(
                store.artifacts,
                store.sources,
                cache,
                min_hits=SELF_IMPRESSION_MIN_EVIDENCE,
                today=now.date().isoformat(),
            )
            return {"self_impressions": int(made)}

        dream = modules.dream.DreamCycle(
            store.dreams,
            config,
            clock=lambda: now,
            log=lambda _message: None,
        )
        run_params = inspect.signature(dream.run).parameters
        run_kwargs: dict[str, Any] = {
            "flush_once": flush_once,
            "pending": lambda: len(buffer.items),
            "now": now,
        }
        if maintenance:
            run_kwargs["maintain"] = maintain
        if "usage" in run_params:
            run_kwargs["usage"] = service.usage_snapshot

        seen_items = list(buffer.items)
        seen_ids: list[str] = []
        for item in seen_items:
            if item.topic_id not in seen_ids:
                seen_ids.append(str(item.topic_id))
        eligible, triage = _triage_snapshot(modules, buffer)

        dream_result = asyncio.run(dream.run(**run_kwargs))

        pending_rows = store.extraction.pending_extractions()
        pending_ids = {str(row["topic_id"]) for row in pending_rows}
        selected_ids = [tid for tid in seen_ids if tid not in pending_ids]
        active = [
            art for art in cache.active("memory") if art.header.family == "memory"
        ]
        queue = store.extraction.queue_counts()
        return _summarize(
            topics=topics,
            seen_ids=seen_ids,
            selected_ids=selected_ids,
            pending_rows=pending_rows,
            eligible=eligible,
            triage=triage,
            provider=provider,
            dream_result=dream_result,
            active=active,
            now=now,
            maintenance=maintenance,
            feature_paths=modules.feature_paths(),
            logger=logger,
            queue=queue,
            self_subject=str(modules.bot_behavior.SELF_SUBJECT),
            service_usage=(
                service.usage_snapshot()
                if hasattr(service, "usage_snapshot")
                else None
            ),
        )
    finally:
        try:
            store.close()
        except Exception:
            pass


def _recorded_index(topics: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for topic in topics:
        truth = topic.get("truth") or {}
        kind = str(truth.get("kind") or "")
        for item in topic.get("recorded") or []:
            text = normalize(str(item.get("text") or ""))
            if not text or text in index:
                continue
            index[text] = {
                "topic_id": str(topic["id"]),
                "kind": kind,
                "fact_key": truth.get("fact_key"),
                "behavior": item.get("bot_behavior"),
            }
    return index


def _summarize(
    *,
    topics: list[dict[str, Any]],
    seen_ids: list[str],
    selected_ids: list[str],
    pending_rows: list[dict[str, Any]],
    eligible: set[str] | None,
    triage: dict[str, Any],
    provider: RecordedProvider,
    dream_result,
    active: list[Any],
    now: datetime.datetime,
    maintenance: bool,
    feature_paths: dict[str, bool],
    logger: EvalLogger,
    queue: dict[str, int],
    self_subject: str,
    service_usage: dict[str, int] | None,
) -> dict[str, Any]:
    by_id = {str(topic["id"]): topic for topic in topics}
    selected = set(selected_ids)
    pending_ids = {
        str(row["topic_id"]) for row in pending_rows if str(row["topic_id"])
    }
    important = {
        tid: bool(topic.get("important")) for tid, topic in by_id.items()
    }
    classes = {tid: str(topic["class"]) for tid, topic in by_id.items()}

    skipped = [tid for tid in seen_ids if tid not in selected]
    eligible_ids = eligible or set()
    skipped_low_value = (
        [tid for tid in skipped if not important.get(tid, False)]
        if eligible is not None
        else None
    )
    skipped_important = (
        [tid for tid in skipped if important.get(tid, False)]
        if eligible is not None
        else None
    )
    skipped_eligible = (
        [tid for tid in eligible_ids if tid not in selected]
        if eligible is not None
        else None
    )

    # Artifact classification is by recorded text, never by dumping payloads.
    recorded_index = _recorded_index(topics)
    extraction: list[tuple[Any, dict[str, Any]]] = []
    self_impressions: list[Any] = []
    unclassified_details: list[dict[str, Any]] = []
    for art in active:
        try:
            text = normalize(_content_of(art))
        except Exception:
            unclassified_details.append({"reason": "content_error"})
            continue
        meta = recorded_index.get(text)
        if meta is not None:
            extraction.append((art, meta))
        elif (
            art.payload.get("level") == "impression"
            and art.header.subject_id == self_subject
            and art.payload.get("bot_behavior")
        ):
            self_impressions.append(art)
        else:
            unclassified_details.append(
                {
                    "level": str(art.payload.get("level") or ""),
                    "subject_id": str(art.header.subject_id or ""),
                    "said_by": str(art.header.said_by or ""),
                    "bot_behavior": str(art.payload.get("bot_behavior") or ""),
                    "derived_from": len(art.header.lineage.derived_from),
                }
            )

    fact_texts: dict[str, set[str]] = {}
    fact_topics: dict[str, list[str]] = {}
    for topic in topics:
        truth = topic.get("truth") or {}
        if truth.get("kind") != "fact" or not truth.get("fact_key"):
            continue
        key = str(truth["fact_key"])
        fact_topics.setdefault(key, []).append(str(topic["id"]))
        for item in topic.get("recorded") or []:
            fact_texts.setdefault(key, set()).add(
                normalize(str(item.get("text") or ""))
            )
    written_texts = {normalize(_content_of(art)) for art, _meta in extraction}
    recalled_keys = sorted(
        key for key, texts in fact_texts.items() if texts & written_texts
    )
    missing_keys = sorted(set(fact_texts) - set(recalled_keys))
    important_fact_recall = (
        len(recalled_keys) / len(fact_texts) if fact_texts else 1.0
    )

    behavior_expected: list[tuple[str, str, str]] = []
    for topic in topics:
        truth = topic.get("truth") or {}
        if truth.get("kind") != "behavior":
            continue
        recorded = (topic.get("recorded") or [{}])[0]
        behavior_expected.append(
            (
                str(topic["id"]),
                str(truth.get("behavior") or ""),
                normalize(str(recorded.get("text") or "")),
            )
        )
    behavior_written: list[str] = []
    behavior_missing: list[str] = []
    artifact_by_text = {
        normalize(_content_of(art)): art for art, _meta in extraction
    }
    for tid, kind, text in behavior_expected:
        art = artifact_by_text.get(text)
        if art is not None and str(art.payload.get("bot_behavior") or "") == kind:
            behavior_written.append(tid)
        else:
            behavior_missing.append(tid)
    behavior_coverage = (
        len(behavior_written) / len(behavior_expected) if behavior_expected else 1.0
    )

    behavior_counts = Counter(
        kind for _tid, kind, _text in behavior_expected
    )
    expected_impression_kinds = {
        kind
        for kind, count in behavior_counts.items()
        if count >= SELF_IMPRESSION_MIN_EVIDENCE
    }
    written_impression_kinds = {
        str(art.payload.get("bot_behavior") or "") for art in self_impressions
    } & expected_impression_kinds
    self_impression_coverage = (
        len(written_impression_kinds) / len(expected_impression_kinds)
        if expected_impression_kinds
        else 1.0
    )

    false_memory = [
        art for art, meta in extraction if meta.get("kind") == "noise"
    ]
    false_memory_rate = (
        len(false_memory) / len(extraction) if extraction else 0.0
    )
    text_counter = Counter(normalize(_content_of(art)) for art, _meta in extraction)
    duplicate_artifacts = sum(count - 1 for count in text_counter.values() if count > 1)
    duplicate_rate = (
        duplicate_artifacts / len(extraction) if extraction else 0.0
    )

    levels = Counter(str(art.payload.get("level") or "") for art, _meta in extraction)
    behaviors = Counter(
        str(art.payload.get("bot_behavior") or "")
        for art, _meta in extraction
        if art.payload.get("bot_behavior")
    )

    pending_ages: list[float] = []
    for row in pending_rows:
        stamp = str(row.get("created_at") or "")
        try:
            created = datetime.datetime.fromisoformat(stamp)
        except ValueError:
            continue
        pending_ages.append(max(0.0, (now - created).total_seconds() / 86400.0))
    oldest_age = round(max(pending_ages), 4) if pending_ages else 0.0
    mean_age = round(sum(pending_ages) / len(pending_ages), 4) if pending_ages else 0.0
    pending_important = [tid for tid in pending_ids if important.get(tid, False)]
    pending_low_value = [tid for tid in pending_ids if not important.get(tid, False)]

    summary = dict(getattr(dream_result, "summary", {}) or {})
    budget = summary.get("budget") if isinstance(summary.get("budget"), dict) else None
    usage_delta = summary.get("usage") if isinstance(summary.get("usage"), dict) else None

    total_tokens = provider.usage_in + provider.usage_out
    seen = len(seen_ids)
    pending_ratio = len(pending_ids) / seen if seen else 0.0

    quality = {
        "important_fact_total": len(fact_texts),
        "important_fact_recalled": len(recalled_keys),
        "important_fact_recall": round(important_fact_recall, 4),
        "missing_fact_keys": missing_keys,
        "missing_fact_topic_ids": sorted(
            tid for key in missing_keys for tid in fact_topics.get(key, [])
        ),
        "missing_fact_topics": {
            key: sorted(fact_topics.get(key, [])) for key in missing_keys
        },
        "behavior_total": len(behavior_expected),
        "behavior_written": len(behavior_written),
        "behavior_coverage": round(behavior_coverage, 4),
        "missing_behavior_topic_ids": sorted(behavior_missing),
        "self_impression_expected_kinds": sorted(expected_impression_kinds),
        "self_impression_written_kinds": sorted(written_impression_kinds),
        "self_impression_coverage": round(self_impression_coverage, 4),
        "false_memory_artifacts": len(false_memory),
        "false_memory_rate": round(false_memory_rate, 4),
        "duplicate_artifacts": duplicate_artifacts,
        "duplicate_rate": round(duplicate_rate, 4),
    }
    checks = {
        "important_fact_recall": important_fact_recall
        >= THRESHOLDS["min_important_fact_recall"],
        "behavior_coverage": behavior_coverage
        >= THRESHOLDS["min_behavior_coverage"],
        "self_impression_coverage": self_impression_coverage
        >= THRESHOLDS["min_self_impression_coverage"],
        "false_memory_rate": false_memory_rate
        <= THRESHOLDS["max_false_memory_rate"],
        "duplicate_rate": duplicate_rate <= THRESHOLDS["max_duplicate_rate"],
        "pending_ratio": pending_ratio <= THRESHOLDS["max_pending_ratio"],
    }
    distribution: dict[str, dict[str, int]] = {}
    for tid, info in (triage.get("scores") or {}).items():
        try:
            score = float(info.get("score", 0))
        except (TypeError, ValueError):
            score = 0.0
        if score <= 0:
            bucket = "0"
        elif score < 2:
            bucket = "1"
        elif score < 4:
            bucket = "2-3"
        else:
            bucket = "4+"
        distribution.setdefault(bucket, {})
        key = classes.get(str(tid), "")
        distribution[bucket][key] = distribution[bucket].get(key, 0) + 1
    return {
        "topics": {
            "seen": seen,
            "seen_by_class": dict(
                sorted(Counter(classes.get(tid, "") for tid in seen_ids).items())
            ),
            "eligible": len(eligible_ids) if eligible is not None else None,
            "selected": len(selected_ids),
            "skipped": len(skipped),
            "skipped_low_value": (
                len(skipped_low_value) if skipped_low_value is not None else None
            ),
            "skipped_important": (
                len(skipped_important) if skipped_important is not None else None
            ),
            "skipped_eligible": (
                len(skipped_eligible) if skipped_eligible is not None else None
            ),
            "selected_low_value": sorted(
                tid for tid in selected_ids if not important.get(tid, False)
            ),
            "pending_topics": len(pending_ids),
            "pending_important_topics": len(pending_important),
            "pending_low_value_topics": len(pending_low_value),
            "pending_topic_ids": sorted(pending_ids),
            "skipped_important_topic_ids": sorted(skipped_important or []),
        },
        "triage": {
            "applied": bool(triage.get("applied")),
            "threshold": triage.get("threshold"),
            "scores": triage.get("scores", {}),
            "distribution": distribution,
        },
        "cost": {
            "extraction_calls": provider.calls,
            "usage_in": provider.usage_in,
            "usage_cached": provider.usage_cached,
            "usage_out": provider.usage_out,
            "usage_total": total_tokens,
            "prompt_chars": provider.prompt_chars,
            "output_chars": provider.output_chars,
            "calls_with_multiple_topics": provider.calls_with_multiple_topics,
            "max_topics_per_call": provider.max_topics_per_call,
            "calls_with_output_overflow": provider.calls_with_overflow,
            "avg_input_tokens_per_call": (
                round(provider.usage_in / provider.calls, 2) if provider.calls else 0
            ),
            "provider_reported": False,
            "token_estimate": "int(chars/1.6)+4*messages",
            "service_usage_snapshot": service_usage,
        },
        "artifacts": {
            "active_memory": len(active),
            "extraction_written": len(extraction),
            "unclassified": len(unclassified_details),
            "unclassified_details": unclassified_details,
            "by_level": dict(sorted(levels.items())),
            "by_behavior": dict(sorted(behaviors.items())),
            "self_impressions": len(self_impressions),
        },
        "quality": quality,
        "pending": {
            "rows": len(pending_rows),
            "topics": len(pending_ids),
            "ratio": round(pending_ratio, 4),
            "oldest_age_days": oldest_age,
            "mean_age_days": mean_age,
            "important_topics": len(pending_important),
            "low_value_topics": len(pending_low_value),
            "by_class": dict(
                sorted(Counter(classes.get(tid, "") for tid in pending_ids).items())
            ),
            "queue": dict(queue),
        },
        "dream": {
            "status": str(getattr(dream_result, "status", "")),
            "batches": int(getattr(dream_result, "batches", 0) or 0),
            "written": int(getattr(dream_result, "written", 0) or 0),
            "error_count": len(getattr(dream_result, "errors", ()) or ()),
            "budget": budget,
            "usage_delta": usage_delta,
        },
        "verdict": {
            "thresholds": dict(THRESHOLDS),
            "checks": checks,
            "acceptable": all(checks.values()),
            "maintenance_run": maintenance,
        },
        "feature_paths": feature_paths,
        "warnings": logger.warning_count,
    }


def _content_of(art) -> str:
    module = sys.modules.get("core.domain.memory.artifact")
    if module is None:
        module = importlib.import_module("core.domain.memory.artifact")
    return module.content_of(art)


# --------------------------------------------------------------------------- #
# Backlog growth scenario
# --------------------------------------------------------------------------- #


def _clone_day(topic: dict[str, Any], day: int) -> dict[str, Any]:
    clone = json.loads(json.dumps(topic))
    clone["id"] = f"{topic['id']}#d{day}"
    start = _parse_time(str(topic["at"])) + datetime.timedelta(days=day - 1)
    clone["at"] = start.isoformat(timespec="seconds")
    return clone


def run_backlog(
    modules: TargetModules,
    topics: list[dict[str, Any]],
    *,
    days: int = 3,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Append only low-value topics for N nights and measure pending growth."""
    base_now = now or _parse_time(FIXED_NOW)
    pool = [
        topic
        for topic in topics
        if str(topic.get("class")) in ("chatter", "backlog")
    ]
    store = modules.store_module.open_store(":memory:")
    per_day: list[dict[str, Any]] = []
    cumulative_records: dict[str, list[dict[str, Any]]] = {}
    cumulative_sources: dict[str, str] = {}
    priority: dict[str, int] = {}
    try:
        for day in range(1, max(1, int(days)) + 1):
            clones = [_clone_day(topic, day) for topic in pool]
            for clone in clones:
                priority[str(clone["id"])] = 2
            sources, _topic_sources, records = seed_corpus(modules, store, clones)
            cumulative_sources.update(sources)
            cumulative_records.update(records)
            buffer = modules.buffer.Buffer("", extraction=store.extraction)
            cache = modules.cache_module.Cache(store.artifacts)
            graph = modules.graph_module.Graph(store.artifacts)
            provider = RecordedProvider(
                cumulative_records, cumulative_sources, priority
            )
            config = _conf_factory()
            service = modules.ingest.IngestService(
                buffer=buffer,
                artifacts=store.artifacts,
                sources=store.sources,
                extraction=store.extraction,
                cache=cache,
                graph=graph,
                journal=EvalJournal(),
                config=config,
                provider_for=lambda _session, p=provider: _async_value(p),
                owner_id=lambda: OWNER_ID,
                logger=EvalLogger(),
            )
            flush_params = inspect.signature(service.flush).parameters

            async def flush_once(reason: str, **kwargs):
                accepted = {
                    key: value for key, value in kwargs.items() if key in flush_params
                }
                return await service.flush(reason, **accepted)

            dream = modules.dream.DreamCycle(
                store.dreams,
                config,
                clock=lambda moment=base_now + datetime.timedelta(days=day - 1): moment,
                log=lambda _message: None,
            )
            moment = base_now + datetime.timedelta(days=day - 1)
            run_kwargs: dict[str, Any] = {
                "flush_once": flush_once,
                "pending": lambda: len(buffer.items),
                "now": moment,
            }
            if "usage" in inspect.signature(dream.run).parameters:
                run_kwargs["usage"] = (
                    service.usage_snapshot
                    if hasattr(service, "usage_snapshot")
                    else None
                )
            asyncio.run(dream.run(**run_kwargs))
            pending_rows = store.extraction.pending_extractions()
            pending_ids = {str(row["topic_id"]) for row in pending_rows}
            ages = []
            for row in pending_rows:
                try:
                    created = datetime.datetime.fromisoformat(
                        str(row.get("created_at") or "")
                    )
                except ValueError:
                    continue
                ages.append(max(0.0, (moment - created).total_seconds() / 86400.0))
            per_day.append(
                {
                    "day": day,
                    "new_topics": len(pool),
                    "pending_topics": len(pending_ids),
                    "pending_rows": len(pending_rows),
                    "oldest_age_days": round(max(ages), 4) if ages else 0.0,
                    "extraction_calls": provider.calls,
                }
            )
        first = per_day[0]["pending_topics"] if per_day else 0
        last = per_day[-1]["pending_topics"] if per_day else 0
        growth = last - first
        return {
            "days": len(per_day),
            "low_value_pool": len(pool),
            "per_day": per_day,
            "pending_delta": growth,
            "growth_per_day": round(growth / max(1, len(per_day) - 1), 2),
            "bounded": bool(growth <= 0),
            "risk": "linear_unbounded" if growth > 0 else "none",
        }
    finally:
        store.close()


async def _async_value(value):
    return value


# --------------------------------------------------------------------------- #
# Public entry point and CLI
# --------------------------------------------------------------------------- #


def run_eval(
    repo: Path | str,
    *,
    label: str = "worktree",
    corpus_path: Path | str = DEFAULT_CORPUS,
    maintenance: bool = True,
    backlog_days: int = 3,
    now: datetime.datetime | None = None,
) -> dict[str, Any]:
    """Run the frozen corpus against one checkout and return content-free metrics."""
    moment = now or _parse_time(FIXED_NOW)
    topics = load_corpus(corpus_path)
    modules = TargetModules(repo)
    main = _drive(modules, topics, moment, maintenance)
    backlog = run_backlog(modules, topics, days=backlog_days, now=moment)
    return {
        "schema": SCHEMA,
        "label": str(label),
        "corpus": corpus_snapshot(corpus_path, topics),
        "environment": {
            "python": platform.python_version(),
            "platform": sys.platform,
            "network": False,
            "model": RecordedProvider.name,
            "clock": FIXED_NOW,
            "harness_sha256": harness_digest(),
            "deterministic": True,
        },
        "feature_paths": main["feature_paths"],
        "config": {
            "dream_max_batches": 100,
            "dream_max_calls": 100,
            "dream_token_budget": 1_000_000,
            "dream_batch_tokens": 6000,
            "flush_batch_cap": 6,
            "self_impression_min_evidence": SELF_IMPRESSION_MIN_EVIDENCE,
            "backlog_days": max(1, int(backlog_days)),
        },
        "cost": main["cost"],
        "topics": main["topics"],
        "triage": main["triage"],
        "artifacts": main["artifacts"],
        "quality": main["quality"],
        "pending": main["pending"],
        "dream": main["dream"],
        "backlog": backlog,
        "verdict": main["verdict"],
        "warnings": main["warnings"],
    }


def _summary_line(report: dict[str, Any]) -> str:
    cost = report["cost"]
    quality = report["quality"]
    pending = report["pending"]
    return (
        f"{report['label']}: calls={cost['extraction_calls']} "
        f"tokens={cost['usage_total']} "
        f"recall={quality['important_fact_recalled']}/"
        f"{quality['important_fact_total']} "
        f"behavior={quality['behavior_written']}/"
        f"{quality['behavior_total']} "
        f"pending={pending['topics']} "
        f"acceptable={report['verdict']['acceptable']}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=".", help="checkout to evaluate")
    parser.add_argument("--label", default="worktree", help="report label")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS))
    parser.add_argument("--output", default="", help="write JSON here")
    parser.add_argument("--backlog-days", type=int, default=3)
    parser.add_argument(
        "--no-self-impression",
        action="store_true",
        help="skip maintenance; used by the write-path regression test",
    )
    args = parser.parse_args(argv)
    report = run_eval(
        args.repo,
        label=args.label,
        corpus_path=args.corpus,
        maintenance=not args.no_self_impression,
        backlog_days=args.backlog_days,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        target = Path(args.output)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text + "\n", encoding="utf-8")
        print(_summary_line(report))
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
