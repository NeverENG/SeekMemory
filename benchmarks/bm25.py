"""BM25 校准、独立验收与索引规模测量；不调用模型或网络。"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from benchmarks.ablation import Cfg, _load, measure
from benchmarks.bm25_cases import CALIBRATION_CASES, CALIBRATION_VALUES, CALIBRATION_WEIGHTS, DISTRACTOR_COUNT
from benchmarks.goldset import build as gold_data
from core.domain.memory.artifact import Artifact, make
from core.domain.memory.graph import Graph
from recall.assemble import build as assemble
from recall.bm25 import BM25Index, DEFAULT_CALIBRATION_C
from recall.retriever import GraphRetriever, HybridRetriever
from recall.score import select
from store.cache import Cache
from store import open_store


@dataclass(frozen=True)
class Sample:
    query: str
    target: Artifact
    pool: list[Artifact]


def memory(text: str, node_id: str, tags: tuple[str, ...] = ()) -> Artifact:
    """使用稳定 ID 和日期构造合成记忆，避免时间/排序干扰比较。"""
    return make("memory", {"text": text, "level": "fact", "tags": list(tags)},
                id=node_id, strength={"weight": 0.5, "arousal": 0.0},
                time={"created": "2026-10-22", "updated": "2026-10-22"})


def calibration_samples() -> list[Sample]:
    """仅构造已指定的五条校准题，不读取独立验收数据。"""
    samples = []
    for number, case in enumerate(CALIBRATION_CASES):
        target = memory(case.target, f"cal_{number}_target")
        distractors = [memory(case.common_prefix + f"常规流程事项第{i}项", f"cal_{number}_{i}")
                       for i in range(DISTRACTOR_COUNT)]
        samples.append(Sample(case.query, target, distractors + [target]))
    return samples


def evaluate(samples: list[Sample], calibration_c: float, weight: float,
             enabled: bool) -> dict:
    """经真实图候选与 select 统计命中、候选噪声、组装长度和延迟。"""
    hits = selected = noise = chars = 0
    elapsed = 0.0
    details = []
    for sample in samples:
        db = open_store(":memory:")
        try:
            cache = Cache(db.artifacts)
            graph = Graph(db.artifacts)
            for art in sample.pool:
                cache.put(art)
            retriever = (HybridRetriever(graph, cache, BM25Index(calibration_c))
                         if enabled else GraphRetriever(graph, cache))
            start = time.perf_counter()
            picked = select(retriever.retrieve(sample.query, sample.pool), sample.query,
                            0.0, k=8, explore=0.0, lexical_weight=weight)
            block = assemble(picked, budget=600)
            elapsed += time.perf_counter() - start
            hit = sample.target.header.id in {art.header.id for art in picked}
            hits += hit
            selected += len(picked)
            noise += sum(art.header.id != sample.target.header.id for art in picked)
            chars += len(block)
            details.append({"target": sample.target.header.id, "hit": hit,
                            "picked": len(picked)})
        finally:
            db.close()
    return {"hits": hits, "total": len(samples), "noise": noise / max(1, selected),
            "chars": chars / max(1, len(samples)),
            "latency_ms": elapsed * 1000 / max(1, len(samples)), "details": details}


def calibrate() -> list[dict]:
    """只用旧黄金集和五条校准题筛选参数；holdout 不参与选择。"""
    samples = calibration_samples()
    db, cache, graph, pool = _load(gold_data())
    try:
        baseline = measure(Cfg("full"), pool, pool, graph, cache)
        rows = []
        for value in CALIBRATION_VALUES:
            for weight in CALIBRATION_WEIGHTS:
                old = measure(Cfg("bm25", bm25=True, calibration_c=value,
                                  lexical_weight=weight), pool, pool, graph, cache)
                lexical = evaluate(samples, value, weight, True)
                eligible = (set(old["misses"]) <= set(baseline["misses"])
                            and old["noise"] <= baseline["noise"]
                            and old["leak"] == baseline["leak"] == 0)
                rows.append({"C": value, "weight": weight, "old_hits": old["hit"],
                             "old_noise": old["noise"], "eligible": eligible,
                             "calibration_hits": lexical["hits"]})
        return rows
    finally:
        db.close()


def legacy_comparison(calibration_c: float, weight: float) -> dict:
    """冻结参数后检查原黄金题逐题不退化、原噪声不增加。"""
    db, cache, graph, pool = _load(gold_data())
    try:
        old = measure(Cfg("full"), pool, pool, graph, cache)
        new = measure(Cfg("bm25", bm25=True, calibration_c=calibration_c,
                          lexical_weight=weight), pool, pool, graph, cache)
        passed = (set(new["misses"]) <= set(old["misses"])
                  and new["noise"] <= old["noise"] and new["leak"] == old["leak"] == 0)
        return {"baseline": old, "enabled": new, "passed": passed}
    finally:
        db.close()


def validate(calibration_c: float, weight: float) -> dict:
    """参数冻结后首次读取独立数据，并验证空证据及语义限制。"""
    from benchmarks.bm25_holdout import HOLDOUT_CASES, NO_RESULT_QUERIES, SEMANTIC_LIMITS

    samples = []
    for case in HOLDOUT_CASES:
        target = memory(case.target.text, case.target.id, case.target.tags)
        pool = [memory(doc.text, doc.id, doc.tags) for doc in case.distractors]
        samples.append(Sample(case.query, target, pool + [target]))
    baseline = evaluate(samples, calibration_c, weight, False)
    enabled = evaluate(samples, calibration_c, weight, True)
    index = BM25Index(calibration_c)
    pool = [art for sample in samples for art in sample.pool]
    index.rebuild(pool)
    empty_ok = all(not index.search(query, pool) for query in NO_RESULT_QUERIES)
    limits_ok = True
    for number, case in enumerate(SEMANTIC_LIMITS):
        art = memory(case.memory, f"semantic_{number}")
        index.rebuild([art])
        limits_ok &= not index.search(case.query, [art])
    return {"baseline": baseline, "enabled": enabled,
            "no_result_queries_pass": empty_ok, "semantic_limits_pass": bool(limits_ok),
            "sha256": hashlib.sha256((ROOT / "benchmarks/bm25_holdout.py").read_bytes()).hexdigest()}


def index_sizes() -> list[dict]:
    """测量 5k/20k 文档的建库、重建和暖查询耗时。"""
    rows = []
    for size in (5000, 20000):
        pool = [memory(f"数据库索引维护记录第{i}号，项目正在进行日常部署", f"size_{i}")
                for i in range(size)]
        index = BM25Index()
        start = time.perf_counter()
        index.rebuild(pool)
        build_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        index.rebuild(pool)
        rebuild_ms = (time.perf_counter() - start) * 1000
        start = time.perf_counter()
        for _ in range(10):
            index.search("数据库索引维护", pool)
        rows.append({"size": size, "build_ms": build_ms, "rebuild_ms": rebuild_ms,
                     "query_ms": (time.perf_counter() - start) * 100})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibrate", action="store_true")
    parser.add_argument("--sizes", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = {"C": DEFAULT_CALIBRATION_C, "weight": 1.0}
    if args.calibrate:
        result["calibration"] = calibrate()
    result["legacy"] = legacy_comparison(DEFAULT_CALIBRATION_C, 1.0)
    result["holdout"] = validate(DEFAULT_CALIBRATION_C, 1.0)
    if args.sizes:
        result["sizes"] = index_sizes()
    encoded = json.dumps(result, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    old, new = result["holdout"]["baseline"], result["holdout"]["enabled"]
    if (not result["legacy"]["passed"]
            or new["hits"] <= old["hits"] or new["noise"] > old["noise"]
            or not result["holdout"]["no_result_queries_pass"]
            or not result["holdout"]["semantic_limits_pass"]):
        raise SystemExit("独立验收未达标；不得使用验收集继续调参。")


if __name__ == "__main__":
    main()
