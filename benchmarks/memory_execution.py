"""Execute offline production paths with fixed fixtures and scoped SQLite stores.

使用固定样本及作用域内关闭的 SQLite 存储执行离线生产路径。
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import time

from .dataset import build, decayed_events
from .memory_corpus import CONFIG, SESSION, _rel_time, _synthetic_pool, to_artifact
from .memory_metrics import observation, summarize
from .memory_target import target


def query(modules, db, cache, graph, text, *, session=SESSION, speaker="owner", private=True):
    """Use the pure entry or the older explicit preview entry / 使用纯查询或旧版本明确预览入口。"""
    args = (cache, graph, db.artifacts, db.sources, session, text, private, CONFIG.get, SESSION, speaker)
    if hasattr(modules.pipeline, "query_block"):
        return modules.pipeline.query_block(*args)
    return modules.pipeline.build_block(*args, dry_run=True)


def seed(modules, db, cache, art, source_id, *, session=SESSION, speaker="owner"):
    """Attach explicit synthetic evidence; Source bodies are never expected context.

附加明确合成证据，Source 正文从来不是期望上下文。
    """
    source = modules.source.Source(source_id, source_id, session, speaker, "user",
                                   f"SOURCE_BODY_ONLY_{source_id}", _rel_time(30)["created"])
    db.sources.append_sources([source])
    art = replace(art, header=replace(art.header, subject_id=speaker,
                                    lineage=modules.artifact.Lineage(sources=(source_id,))))
    db.artifacts.commit(art, expected_revision=0, op="create", source_ids=(source_id,))
    cache.put(art)
    return art


def component_rows(modules, cache, graph, pool, queries, *, hybrid):
    """Measure retrieval/assembly only, independently of privacy claims / 仅测检索和组装，不据此证明隐私。"""
    cls = modules.retriever.HybridRetriever if hybrid else modules.retriever.GraphRetriever
    retriever = cls(graph, cache)
    rows = []
    for index, item in enumerate(queries):
        start = time.perf_counter()
        selected = modules.score.select(retriever.retrieve(item.text, pool), item.text, 0.0,
                                        k=8, explore=0.0, lexical_weight=1.0)
        picked = list({a.header.id: a for a in modules.gate.pinned(cache) + selected}.values())
        block = modules.assemble.build(picked, budget=600)
        rows.append(observation(f"q{index:02}", tuple(item.expect),
                                [modules.artifact.content_of(a) for a in picked], block,
                                level_hit=bool(item.expect_level and any(a.payload.get("level") == item.expect_level for a in picked)),
                                retrieved=len(selected), elapsed_ms=(time.perf_counter() - start) * 1000))
    return rows


def privacy_rows(modules):
    """Exercise full disclosure with protected cases and nonempty positive controls.

通过完整披露路径验证受保护场景和必须非空的正常披露正例。
    """
    cases = (
        ("secret", "secret", {"ref": "vault:test", "shadow_text": "PROTECTED_SECRET"}, "shared", "other", "g1", "g2", "secret", "PROTECTED_SECRET", ""),
        ("shadow", "memory", {"text": "PROTECTED_SHADOW", "level": "fact"}, "shadow", "other", "g1", "g2", "PROTECTED_SHADOW", "PROTECTED_SHADOW", ""),
        ("pinned", "memory", {"text": "PROTECTED_PINNED", "level": "impression"}, "shared", "owner", "g1", "g2", "hello", "PROTECTED_PINNED", ""),
        ("persona", "persona", {"text": "PROTECTED_PERSONA"}, "shared", "bot:self", "g1", "g2", "hello", "PROTECTED_PERSONA", ""),
        ("designated_other", "designated", {"text": "PROTECTED_DESIGNATED", "trigger": "reminder"}, "shared", "other", "g1", "g2", "reminder", "PROTECTED_DESIGNATED", ""),
        ("designated_same", "designated", {"text": "VISIBLE_REMINDER", "trigger": "reminder"}, "private", "owner", SESSION, SESSION, "reminder", "", "VISIBLE_REMINDER"),
        ("memory_same", "memory", {"text": "VISIBLE_MEMORY", "level": "fact", "tags": ["VISIBLE_MEMORY"]}, "private", "owner", SESSION, SESSION, "VISIBLE_MEMORY", "", "VISIBLE_MEMORY"),
    )
    rows = []
    for identity, family, payload, scope, subject, origin, destination, text, forbidden, required in cases:
        db = modules.store.open_store(":memory:")
        try:
            cache, graph = modules.cache.Cache(db.artifacts), modules.graph.Graph(db.artifacts)
            art = modules.artifact.make(family, payload, id=f"privacy_{identity}", scope=scope, said_by=subject, time=_rel_time(30))
            seed(modules, db, cache, art, f"privacy_source_{identity}", session=origin, speaker=subject)
            block, _ = query(modules, db, cache, graph, text, session=destination, private=destination == SESSION)
            rows.append({"id": identity, "passed": (not forbidden or forbidden not in block)
                         and (not required or required in block) and "SOURCE_BODY_ONLY_" not in block})
        finally:
            db.close()
    return rows


def execute(repo: Path) -> dict:
    """Run one checkout; release every store before returning aggregate observations.

执行一个代码版本，返回聚合观察前关闭全部存储。
    """
    with target(repo) as modules:
        db = modules.store.open_store(":memory:")
        try:
            cache, graph = modules.cache.Cache(db.artifacts), modules.graph.Graph(db.artifacts)
            events, queries = build()
            for index, event in enumerate(events):
                art = to_artifact(event)
                if event.kind == "secret":
                    art = replace(art, header=replace(art.header, family="secret"),
                                  payload={"ref": f"vault:fixture:{index}", "shadow_text": event.text})
                seed(modules, db, cache, art, f"sample_source_{index:02}")
            pool = [a for a in cache.active() if a.header.family != "secret"]
            paths = {}
            for name, hybrid in (("graph_components", False), ("bm25_components", True)):
                rows = component_rows(modules, cache, graph, pool, queries, hybrid=hybrid)
                paths[name] = {"rows": rows, "summary": summarize(rows)}
            rows = []
            for index, item in enumerate(queries):
                start = time.perf_counter()
                block, info = query(modules, db, cache, graph, item.text)
                picked = [db.artifacts.get(identity) for identity in dict.fromkeys((*info["picked_ids"], *info["pinned_ids"]))]
                row = observation(f"q{index:02}", tuple(item.expect), [modules.artifact.content_of(a) for a in picked], block,
                                  level_hit=bool(item.expect_level and any(a.payload.get("level") == item.expect_level for a in picked)),
                                  chars_limit=int(600 * (1.4 if info["mode"] == "loose" else 1.0)),
                                  retrieved=info["picked"], elapsed_ms=(time.perf_counter() - start) * 1000)
                row["source_leak"] = "SOURCE_BODY_ONLY_" in block
                rows.append(row)
            paths["full_pipeline"] = {"rows": rows, "summary": summarize(rows)}
            scaled = []
            for size in (50, 200, 500, 1000):
                sample = _synthetic_pool(size)
                picked = modules.score.select([(a, 0.0) for a in sample], "我今天加班到很晚", 0.0, k=8, explore=0.0)
                scaled.append({"size": size, "full_chars": sum(len(modules.artifact.content_of(a)) for a in sample),
                               "injected_chars": len(modules.assemble.build(picked, budget=600))})
            high = [to_artifact(e).header.strength.weight for e in events if e.mentions >= 5]
            low = [to_artifact(e).header.strength.weight for e in events if e.mentions <= 2]
            decay = decayed_events(events)
            return {"paths": paths, "privacy": privacy_rows(modules), "scale": scaled,
                    "fixture_weight_ratio": (sum(high) / len(high)) / (sum(low) / len(low)),
                    "retention": {"important_kept": sum(e.importance >= 0.7 and r > 0.3 for e, r in decay),
                                  "important_total": sum(e.importance >= 0.7 for e, _ in decay),
                                  "trivial_forgotten": sum(e.importance <= 0.2 and r < 0.3 for e, r in decay),
                                  "trivial_total": sum(e.importance <= 0.2 for e, _ in decay)}}
        finally:
            db.close()
