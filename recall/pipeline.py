"""Query candidates, rank, disclose and assemble; only the legacy build wrapper records injection.

查询候选、排序、披露及组装，仅旧 build 包装明确记录注入。
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

try:  # Plugin namespace / 插件命名空间。
    from ..app.ports import ArtifactCache, ArtifactStore, Retriever, SourceStore
    from ..core.disclosure import (
        DisclosureLevel,
        RecallScene,
        decide,
        safe_text,
        scope_prior,
    )
    from ..core.graph import Graph
    from ..core.bot_behavior import trusted_self_persona
    from ..recall.assemble import build_with_meta as assemble_text_meta
    from ..recall.designated import deliverable, mark_given
    from ..recall.drift import best_of as drift_best
    from ..recall.drift import should_drift
    from ..recall.gate import pinned
    from ..recall.history import trajectory
    from ..recall.intent import intent_of, is_profile_recall, is_topic_recall
    from ..recall.retriever import GraphRetriever, HybridRetriever
    from ..recall.scope import visible
    from ..recall.temporal import filter_valid, in_window, query_window
    from ..recall.score import select
    from ..recall.source_query import query_recent
except ImportError:  # Top-level package / 顶层包。
    from app.ports import ArtifactCache, ArtifactStore, Retriever, SourceStore
    from core.disclosure import (
        DisclosureLevel,
        RecallScene,
        decide,
        safe_text,
        scope_prior,
    )
    from core.graph import Graph
    from core.bot_behavior import trusted_self_persona

    from recall.assemble import build_with_meta as assemble_text_meta
    from recall.designated import deliverable, mark_given
    from recall.drift import best_of as drift_best
    from recall.drift import should_drift
    from recall.gate import pinned
    from recall.history import trajectory
    from recall.intent import intent_of, is_profile_recall, is_topic_recall
    from recall.retriever import GraphRetriever, HybridRetriever
    from recall.scope import visible
    from recall.temporal import filter_valid, in_window, query_window
    from recall.score import select
    from recall.source_query import query_recent

Conf = Callable[[str, Any], Any]


from .selection import _conf_bool, subject_of, recent_context
from .source_fallback import supplement
from .disclosure import disclose
from .context_recording import record_context


def query_block(
    cache: ArtifactCache,
    graph: Graph,
    artifacts: ArtifactStore,
    sources: SourceStore,
    umo: str,
    text: str,
    private: bool,
    conf: Conf,
    owner_umo: str,
    speaker: str = "",
    log: Callable[[str], None] = lambda _msg: None,
    *,
    hybrid_retriever: Retriever | None = None,
) -> tuple[str, dict]:
    """Read candidates, rank, disclose and assemble context without memory writes / 读取候选、排序、披露并组装上下文，不写入记忆。"""
    lookup = sources.source_umo
    subject = subject_of(speaker, owner_umo)
    owner_id = str(owner_umo or "").split(":")[-1] if owner_umo else ""
    scene = RecallScene(umo, str(speaker or ""), owner_id, (str(speaker or ""),))
    pinned_arts = visible(pinned(cache, subject), umo, owner_umo, lookup)
    pool = [
        art
        for art in visible(cache.active(), umo, owner_umo, lookup)
        if art.header.family != "relationship"
        and deliverable(art, text, private)
    ]
    pool = filter_valid(pool)
    window = query_window(text)
    if window is not None:
        pool = [
            art for art in pool
            if art.header.family != "memory" or in_window(art, window)
        ]
    source_enabled = _conf_bool(conf, "source_recall_enabled", True)
    if not pool and not pinned_arts and not source_enabled:
        return "", {
            "mode": "none",
            "picked": 0,
            "pinned": 0,
            "chars": 0,
            "picked_ids": (),
            "pinned_ids": (),
            "disclosure": {},
            "fallback": "",
            "candidates": 0,
            "gate": {"evaluated": False, "passed": 0, "rejected": 0, "threshold": 0.0},
        }

    designated = [a for a in pool if a.header.family == "designated"]
    pool = [a for a in pool if a.header.family != "designated"]

    mode = intent_of(text)
    picked: list = []
    candidates: list = []
    gate_info = {"evaluated": False, "passed": 0, "rejected": 0, "threshold": 0.0}
    if mode != "none" and pool:
        lexical_weight = 2.0
        if bool(conf("bm25_enabled", True)):
            retriever = hybrid_retriever or HybridRetriever(graph, cache)
            lexical_weight = float(conf("bm25_weight", 1.0))
        else:
            retriever = GraphRetriever(graph, cache)
        candidates = retriever.retrieve(text, pool)
        candidates = [
            type(candidate)(
                candidate.artifact,
                candidate.activation * scope_prior(candidate.artifact),
                candidate.lexical * scope_prior(candidate.artifact),
            )
            for candidate in candidates
        ]
        loose = mode == "loose"
        picked = select(
            candidates,
            text,
            0.0,
            k=int(conf("recall_k", 8)) + (2 if loose else 0),
            explore=float(conf("explore_rate", 0.1)),
            gate=True,
            min_ev_abs=float(conf("recall_min_ev_abs", 0.5)),
            min_ev_rel=0.2 if loose else float(conf("recall_min_ev_rel", 0.3)),
            lexical_weight=lexical_weight,
            diagnostics=gate_info,
        )

    # Preserve explicit recent-context fallback and optional spontaneous recall.
    # 保留明确近期上下文回退及可选偶然浮现。
    fallback = ""
    if not picked:
        fallback_subject = owner_id if subject == "owner" else subject
        if is_profile_recall(text):
            picked = recent_context(pool, fallback_subject, profile=True)
            fallback = "recent_profile" if picked else ""
        elif is_topic_recall(text):
            picked = recent_context(pool, fallback_subject)
            fallback = "recent_topic" if picked else ""

    if not picked and should_drift(text, seed=text):
        one = drift_best(pool, seed=text)
        if one is not None:
            picked = [one]
            log(f"主动想起：{one.header.id}")

    overrides: dict[str, str] = {}
    disclosure_info: dict[str, str] = {}

    def apply_disclosure(arts: list, relevance: float) -> list:
        return disclose(arts, relevance, scene=scene, sources=sources, umo=umo, owner_umo=owner_umo,
                        overrides=overrides, disclosure_info=disclosure_info)

    source_info = supplement(
        picked, mode=mode, text=text, sources=sources, artifacts=artifacts, conf=conf,
        umo=umo, owner_umo=owner_umo, speaker=speaker, private=private,
        lookup=lookup, window=window, log=log,
    ) if source_enabled else None

    safe_pinned = apply_disclosure(pinned_arts, 1.0)
    safe_designated = apply_disclosure(designated, 1.0)
    safe_picked = apply_disclosure(
        picked, 1.0 if mode != "none" else 0.5
    )
    picked = safe_picked

    budget = int(conf("budget_chars", 600))
    notes = {}
    for art in safe_pinned + picked:
        try:
            if str(art.payload.get("level") or "") == "impression":
                note = trajectory(cache, art)
                if note:
                    notes[art.header.id] = note
        except Exception:  # noqa: BLE001 - Optional trajectory / 可选变化说明。
            continue
    block, final_ids, dropped_ids = assemble_text_meta(
        safe_pinned + safe_designated + picked,
        budget=int(budget * (1.4 if mode == "loose" else 1.0)),
        text=text,
        is_private=private,
        notes=notes,
        overrides=overrides,
    )
    info = {
        "designated_ids": tuple(art.header.id for art in safe_designated + picked
                                if art.header.family == "designated" and art.header.id in final_ids),
        "mode": mode,
        "picked": len(picked),
        "pinned": len(safe_pinned),
        "chars": len(block),
        "drift": bool(picked) and not designated,
        "picked_ids": tuple(a.header.id for a in picked),
        "final_ids": final_ids,
        "dropped_ids": dropped_ids,
        "disclosure": disclosure_info,
        "pinned_ids": tuple(a.header.id for a in safe_pinned),
        "fallback": fallback,
        "candidates": len(candidates),
        "gate": gate_info,
    }
    if source_info is not None:
        info["source_recall"] = source_info
    return block, info


def build_block(
    cache: ArtifactCache, graph: Graph, artifacts: ArtifactStore, sources: SourceStore,
    umo: str, text: str, private: bool, conf: Conf, owner_umo: str, speaker: str = "",
    log: Callable[[str], None] = lambda _msg: None, *, dry_run: bool = False,
    hybrid_retriever: Retriever | None = None,
) -> tuple[str, dict]:
    """Keep legacy query-plus-injection semantics; dry_run skips recording.

    保留旧查询加注入记录语义，dry_run 跳过记录；成功返回值及原参数保持兼容。
    """
    block, info = query_block(cache, graph, artifacts, sources, umo, text, private, conf,
                              owner_umo, speaker, log, hybrid_retriever=hybrid_retriever)
    if not dry_run:
        record_context(artifacts, cache, block, info)
    return block, info
