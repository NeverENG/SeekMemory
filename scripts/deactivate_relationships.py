"""Forget active relationship heads before binary rollback; own the store and preserve evidence/history.

在回滚程序前遗忘有效关系头部，拥有存储并保留证据及历史。
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.artifact import revise  # noqa: E402
from store import open_store  # noqa: E402


def deactivate_relationships(db_path: str) -> tuple[int, int, int]:
    """Commit each active relationship as forgotten with CAS; report counts and close storage.

    以预期版本提交将每个有效关系设为遗忘，报告计数并关闭存储。
    """
    store = open_store(str(db_path))
    try:
        active = store.artifacts.list(family="relationship", state="active")
        forgotten = 0
        failed = 0
        for art in active:
            replacement = revise(art, state="forgotten")
            try:
                store.artifacts.commit(
                    replacement,
                    expected_revision=art.header.revision,
                    op="forget",
                    reason="offline relationship rollback",
                    source_ids=tuple(replacement.header.lineage.sources),
                )
            except Exception:  # noqa: BLE001 - report bounded counts only
                failed += 1
            else:
                forgotten += 1
        return len(active), forgotten, failed
    finally:
        store.close()


def main(argv: Sequence[str] | None = None) -> int:
    """Require explicit confirmation, run offline deactivation and fail if any commit failed.

    要求明确确认，执行离线停用，任一提交失败则返回失败。
    """
    parser = argparse.ArgumentParser(
        description="Forget active Relationship Artifacts before binary rollback."
    )
    parser.add_argument("--db", required=True)
    parser.add_argument("--confirmed", action="store_true", required=True)
    args = parser.parse_args(argv)
    active, forgotten, failed = deactivate_relationships(args.db)
    print(f"active={active} forgotten={forgotten} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
