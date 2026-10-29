"""Migrate an explicitly supplied legacy queue into Source/extraction state; own and close storage.

将明确给定的旧队列迁入 Source 及抽取状态，拥有并关闭存储。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from perceive.buffer import Buffer  # noqa: E402
from store import open_store  # noqa: E402


def main() -> int:
    """Delegate the existing queue migration and report migrated/pending counts.

    委托既有队列迁移，报告已迁移及待处理数量。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="SeekMemory SQLite database path")
    parser.add_argument("--pending", required=True, help="Legacy pending.json path")
    args = parser.parse_args()
    db = open_store(args.db)
    try:
        buffer = Buffer(args.pending, extraction=db.extraction)
        migrated = buffer.migrate_legacy()
        print(f"migrated={migrated} pending={len(buffer.items)}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
