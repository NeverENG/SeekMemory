"""Migrate legacy pending.json rows into immutable Source and extraction_state."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from perceive.buffer import Buffer  # noqa: E402
from store.db import DB  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="SeekMemory SQLite database path")
    parser.add_argument("--pending", required=True, help="Legacy pending.json path")
    args = parser.parse_args()
    db = DB(args.db)
    try:
        buffer = Buffer(args.pending, db=db)
        migrated = buffer.migrate_legacy()
        print(f"migrated={migrated} pending={len(buffer.items)}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
