"""Discover flat test files; explicit layer suffixes override legacy names.

发现平铺测试文件；显式层级后缀优先于旧名称规则。
"""

from __future__ import annotations

from pathlib import Path

ALL_LAYERS = ("unit", "contract", "conformance", "integration", "host", "smoke")
SMOKE = {"test_package.py", "test_eval_harness.py", "test_smoke.py"}
CONTRACT = {"test_public_interfaces.py", "test_runtime_host_contract.py"}
INTEGRATION_MARKERS = (
    "e2e", "absorb", "attention", "astrbot", "continuity", "dream_eval",
    "failure", "group", "privacy", "identity", "lineage", "migration",
    "kernel", "recall", "self_impression", "reinforcement", "run_recorder",
    "runtime_", "temporal", "webui", "console",
)


def _test_files() -> list[Path]:
    return sorted(Path(__file__).resolve().parent.glob("test_*.py"))


def _layer_for(path: Path) -> str:
    name = path.name
    for layer in ALL_LAYERS:
        if name.endswith(f"_{layer}.py"):
            return layer
    if name in SMOKE:
        return "smoke"
    if name in CONTRACT or name.endswith("_contract.py"):
        return "contract"
    if "conformance" in name:
        return "conformance"
    if name.endswith("_host.py"):
        return "host"
    if any(marker in name for marker in INTEGRATION_MARKERS):
        return "integration"
    return "unit"


def files_for(layer: str) -> tuple[str, ...]:
    """Return one layer's files, or all files exactly once / 返回一层或全部文件，每个文件一次。"""
    files = _test_files()
    if layer == "all":
        return tuple(path.name for path in files)
    if layer not in ALL_LAYERS:
        raise ValueError(f"unknown test layer: {layer}")
    return tuple(path.name for path in files if _layer_for(path) == layer)
