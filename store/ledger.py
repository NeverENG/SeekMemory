"""Serialize and append the existing hash chain; shared-transaction helpers never commit independently.

序列化并追加现有哈希链，共享事务帮助函数不独立提交。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

try:
    from .sqlite import SqliteRepository, now_iso
except ImportError:
    from sqlite import SqliteRepository, now_iso


def chain_payload(
    at: str,
    op: str,
    entity: str,
    before: str | None,
    after: str | None,
    reason: str,
) -> str:
    """Encode the existing canonical ledger fields without changing bytes / 编码既有规范账本字段，不改变字节形式。"""
    return json.dumps(
        [at, op, entity, before, after, reason],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def chain_hash(prev_hash: str, payload: str) -> str:
    """Hash the previous hash and canonical payload using the existing format / 按既有格式计算前序哈希及规范内容的哈希。"""
    return hashlib.sha256((prev_hash + payload).encode("utf-8")).hexdigest()[:16]


def append_ledger_conn(
    conn: sqlite3.Connection,
    op: str,
    entity: str,
    before: str | None,
    after: str | None,
    reason: str,
    at: str = "",
) -> None:
    """Append within a caller-owned transaction without committing it / 在调用方事务内追加账本，不独立提交。"""
    moment = at or now_iso()
    row = conn.execute(
        "SELECT self_hash FROM ledger ORDER BY seq DESC LIMIT 1"
    ).fetchone()
    previous = str(row["self_hash"]) if row is not None else ""
    payload = chain_payload(moment, op, entity, before, after, reason)
    conn.execute(
        "INSERT INTO ledger(at, op, entity, before_hash, after_hash, reason, "
        "prev_hash, self_hash) VALUES(?, ?, ?, ?, ?, ?, ?, ?)",
        (
            moment,
            op,
            entity,
            before,
            after,
            reason,
            previous,
            chain_hash(previous, payload),
        ),
    )


class LedgerRepository(SqliteRepository):
    """Own append-only ledger reads and independent append transactions / 管理追加式账本读取及独立的追加事务。"""

    def last_hash(self) -> str:
        """Read the latest stored ledger hash / 读取最新已存账本哈希。"""
        row = self.conn.execute(
            "SELECT self_hash FROM ledger ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        return str(row["self_hash"]) if row is not None else ""

    def append(
        self,
        op: str,
        entity: str,
        before: str | None,
        after: str | None,
        reason: str,
    ) -> None:
        """Append a ledger entry through the repository transaction / 通过仓储事务追加账本条目。"""
        with self.conn:
            append_ledger_conn(self.conn, op, entity, before, after, reason)

    def entries(self) -> list[sqlite3.Row]:
        """Read ledger entries in append order / 按追加顺序读取账本条目。"""
        return self.conn.execute(
            "SELECT at, op, entity, before_hash, after_hash, reason, prev_hash, "
            "self_hash FROM ledger ORDER BY seq"
        ).fetchall()

    def verify(self) -> bool:
        """Check the stored ledger chain without changing it / 检查已存账本链，不进行修改。"""
        previous = ""
        for row in self.entries():
            payload = chain_payload(
                str(row["at"]),
                str(row["op"]),
                str(row["entity"]),
                row["before_hash"],
                row["after_hash"],
                str(row["reason"]),
            )
            expected = chain_hash(previous, payload)
            if str(row["prev_hash"]) != previous or str(row["self_hash"]) != expected:
                return False
            previous = expected
        return True


class Ledger:
    """Keep the existing ledger convenience entry over a repository / 在仓储之上保留既有账本便捷入口。"""

    def __init__(self, repository: LedgerRepository) -> None:
        self.repository = repository

    def append(
        self,
        op: str,
        entity: str,
        before: str | None = None,
        after: str | None = None,
        reason: str = "",
    ) -> str:
        """Append a ledger entry through the repository transaction / 通过仓储事务追加账本条目。"""
        self.repository.append(op, entity, before, after, reason)
        return self.last_hash()

    def last_hash(self) -> str:
        """Read the latest stored ledger hash / 读取最新已存账本哈希。"""
        return self.repository.last_hash()

    def verify(self) -> bool:
        """Check the stored ledger chain without changing it / 检查已存账本链，不进行修改。"""
        return self.repository.verify()
