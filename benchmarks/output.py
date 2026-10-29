"""Allocate independent ignored report paths for legacy exploratory runners.

为旧探索跑分分配独立且忽略跟踪的报告路径。
"""

from pathlib import Path
import tempfile


def report_path(name: str) -> Path:
    """Preserve every existing report; the caller owns writing the new file / 保留全部已有报告，由调用方写新文件。"""
    root = Path(__file__).resolve().parents[1] / ".tmp/benchmarks"
    root.mkdir(parents=True, exist_ok=True)
    return Path(tempfile.mkdtemp(prefix=f"{name}_", dir=root)) / f"{name}.md"
