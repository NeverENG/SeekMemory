"""Atomically publish a consistent SQLite snapshot, including WAL contents.

原子发布包含 WAL 内容的一致 SQLite 快照。
"""
from __future__ import annotations
import argparse
from contextlib import closing
import os
import sqlite3
import tempfile
from pathlib import Path


def snapshot(source: str, destination: str) -> None:
    """Close both handles before publishing; failures preserve the old destination.

关闭两端连接后才发布，失败保留原目标文件。
    """
    src_path = Path(source).expanduser().resolve()
    dst_path = Path(destination).expanduser().absolute()
    if not src_path.exists():
        raise FileNotFoundError(str(src_path))
    if src_path == dst_path.resolve() or (dst_path.exists() and src_path.samefile(dst_path)):
        raise ValueError("snapshot source and destination must differ")
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=f".{dst_path.name}.", suffix=".tmp", dir=dst_path.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        with closing(sqlite3.connect(src_path.as_uri() + "?mode=ro", uri=True)) as src:
            with closing(sqlite3.connect(temporary)) as dst:
                src.backup(dst)
        os.replace(temporary, dst_path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args()
    snapshot(args.source, args.destination)
    print(f"snapshot: {args.destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
