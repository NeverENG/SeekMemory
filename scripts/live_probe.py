"""Read a supplied database through a read-only connection; close it before returning aggregate diagnostics.

通过只读连接读取给定数据库，返回聚合诊断前关闭连接。
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from store.ledger import chain_hash, chain_payload  # noqa: E402


def _count(conn, table, where="", args=()):
    try:
        sql = f"SELECT COUNT(*) FROM {table}"
        if where:
            sql += " WHERE " + where
        row = conn.execute(sql, args).fetchone()
        return int(row[0] if row else 0)
    except sqlite3.Error:
        return 0


def _ledger_ok(conn):
    try:
        rows = conn.execute(
            "SELECT at, op, entity, before_hash, after_hash, reason, prev_hash, self_hash "
            "FROM ledger ORDER BY seq"
        ).fetchall()
    except sqlite3.Error:
        return False
    previous = ""
    for row in rows:
        payload = chain_payload(str(row[0]), str(row[1]), str(row[2]),
                                row[3], row[4], str(row[5]))
        expected = chain_hash(previous, payload)
        if str(row[6]) != previous or str(row[7]) != expected:
            return False
        previous = expected
    return True


def probe(db_path, label=""):
    """Read counts, persona revision and ledger integrity without exporting message bodies.

    读取计数、人格版本及账本完整性，不导出消息正文。
    """
    path = Path(db_path).expanduser()
    if not path.exists():
        raise FileNotFoundError(str(path))
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        persona = conn.execute(
            "SELECT id, revision, state FROM nodes WHERE family='persona' "
            "ORDER BY revision DESC LIMIT 1"
        ).fetchone()
        pending = conn.execute(
            "SELECT state, COUNT(*) FROM extraction_state GROUP BY state"
        ).fetchall()
        return {
            "label": label or str(path),
            "db_bytes": path.stat().st_size,
            "sources": _count(conn, "sources"),
            "nodes": _count(conn, "nodes"),
            "active_nodes": _count(conn, "nodes", "state='active'"),
            "memories": _count(conn, "nodes", "family='memory'"),
            "persona": ({
                "id": str(persona[0]),
                "revision": int(persona[1]),
                "state": str(persona[2]),
            } if persona else None),
            "extraction": {str(row[0]): int(row[1]) for row in pending},
            "artifact_versions": _count(conn, "artifact_versions"),
            "ledger_rows": _count(conn, "ledger"),
            "ledger_ok": _ledger_ok(conn),
        }
    finally:
        conn.close()


def main():
    """Print a read-only probe as JSON or key/value lines.

    以 JSON 或键值行输出只读检查。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="database path")
    parser.add_argument("--label", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    result = probe(args.db, args.label)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
          if args.json else "\n".join(f"{key}: {value}" for key, value in result.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
