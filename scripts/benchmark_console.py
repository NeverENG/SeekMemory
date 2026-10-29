"""Measure graph projection with isolated synthetic SQLite data and no host/model calls.

使用隔离合成 SQLite 数据测量图投影，不调用宿主或模型。
"""
from __future__ import annotations

import argparse
import importlib
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))
make = importlib.import_module(f"{ROOT.name}.core.artifact").make
open_store = importlib.import_module(f"{ROOT.name}.store").open_store
graph = importlib.import_module(f"{ROOT.name}.services.console_projection").graph


def measure(count: int, samples: int, limit: int = 120) -> dict:
    """Own temporary storage for the measurement and return aggregate latency/allocation counts.

    在测量期间拥有临时存储，返回聚合耗时及分配计数。
    """
    with tempfile.TemporaryDirectory(prefix="seekmemory-graph-bench-") as folder:
        store = open_store(str(Path(folder) / "memory.db"))
        try:
            for i in range(count):
                store.artifacts.upsert(make(
                    "memory", {"text": f"Synthetic benchmark memory {i}", "level": "fact"},
                    id=f"bench-{i:07d}", subject_id=f"group-{i % 100}",
                ))
            for i in range(count):
                for delta in (1, 2):
                    store.artifacts.add_edge(f"bench-{i:07d}", f"bench-{(i + delta) % count:07d}", "related", 1)
            times = []
            for _ in range(samples):
                started = time.perf_counter()
                result = graph(store.artifacts, limit=limit)
                times.append((time.perf_counter() - started) * 1000)
            tracemalloc.start()
            graph(store.artifacts, limit=limit)
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            return {
                "artifacts": count, "storedEdges": count * 2, "readLimit": limit,
                "snapshotNodes": len(result["nodes"]), "snapshotEdges": len(result["edges"]),
                "medianMs": statistics.median(times), "maxMs": max(times),
                "peakPythonBytes": peak, "timesMs": times,
                "notes": "Synthetic local SQLite; excludes host HTTP, JSON serialization and browser. Memory is traced Python allocation, not RSS.",
            }
        finally:
            store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nodes", type=int, default=10000)
    parser.add_argument("--samples", type=int, default=10)
    parser.add_argument("--limit", type=int, choices=(40, 80, 120), default=120)
    args = parser.parse_args()
    if not 1000 <= args.nodes <= 100000 or not 1 <= args.samples <= 100:
        parser.error("nodes must be 1000..100000; samples must be 1..100")
    print(json.dumps(measure(args.nodes, args.samples, args.limit), indent=2))
