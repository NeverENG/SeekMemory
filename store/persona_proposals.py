"""Store plain-text persona drafts independently of artifact revisions."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

try:
    from .sqlite import SqliteRepository
except ImportError:  # Standalone store import.
    from sqlite import SqliteRepository


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PersonaProposalRepository(SqliteRepository):
    @staticmethod
    def _record(row):
        if row is None:
            return None
        value = dict(row)
        value["diff"] = json.loads(value["diff"])
        return value

    def create(self, *, subject_key: str, persona_id: str, base_revision: int,
               old_text: str, new_text: str, diff: list[dict], reason: str) -> dict:
        if not subject_key or not new_text.strip() or len(new_text) > 2000 or len(old_text) > 2000:
            raise ValueError("invalid_proposal_text")
        encoded = json.dumps(diff, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) > 8000:
            raise ValueError("proposal_diff_too_long")
        stamp = _now()
        with self.conn:
            existing = self.conn.execute(
                "SELECT * FROM persona_proposals WHERE subject_key=? AND persona_id=? "
                "AND base_revision=? AND new_text=? AND status='pending' "
                "AND (expires_at IS NULL OR expires_at>?) ORDER BY created_at LIMIT 1",
                (subject_key, persona_id, base_revision, new_text, stamp),
            ).fetchone()
            if existing is not None:
                return self._record(existing)
            proposal_id = uuid4().hex
            self.conn.execute(
                "INSERT INTO persona_proposals "
                "(id,subject_key,persona_id,base_revision,old_text,new_text,diff,reason,"
                "created_at,expires_at,status,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,NULL,'pending',?)",
                (proposal_id, subject_key, persona_id, base_revision, old_text,
                 new_text, encoded, reason[:300], stamp, stamp),
            )
            return self._record(self.conn.execute(
                "SELECT * FROM persona_proposals WHERE id=?", (proposal_id,)
            ).fetchone())

    def list_status(self, subject_key: str, status: str = "pending",
                    limit: int = 20) -> list[dict]:
        if status not in ("pending", "approved", "rejected", "expired", "applying"):
            raise ValueError("invalid_proposal_status")
        expiry = "AND (expires_at IS NULL OR expires_at>?) " if status == "pending" else ""
        args = (subject_key, status, _now(), max(1, min(20, int(limit)))) if expiry else (
            subject_key, status, max(1, min(20, int(limit)))
        )
        rows = self.conn.execute(
            "SELECT * FROM persona_proposals WHERE subject_key=? AND status=? " + expiry +
            "ORDER BY created_at,id LIMIT ?", args,
        ).fetchall()
        return [self._record(row) for row in rows]

    def get(self, subject_key: str, proposal_id: str) -> dict | None:
        return self._record(self.conn.execute(
            "SELECT * FROM persona_proposals WHERE subject_key=? AND id=?",
            (subject_key, proposal_id),
        ).fetchone())

    def transition(self, subject_key: str, proposal_id: str, source: str,
                   target: str, *, actor: str = "", revision: int | None = None) -> bool:
        with self.conn:
            cur = self.conn.execute(
                "UPDATE persona_proposals SET status=?,updated_at=?,actor=?,approved_revision=? "
                "WHERE subject_key=? AND id=? AND status=?",
                (target, _now(), actor, revision, subject_key, proposal_id, source),
            )
        return cur.rowcount == 1

    def revise(self, subject_key: str, proposal_id: str,
               new_text: str, diff: list[dict]) -> bool:
        encoded = json.dumps(diff, ensure_ascii=False, separators=(",", ":"))
        if not new_text.strip() or len(new_text) > 2000 or len(encoded) > 8000:
            raise ValueError("invalid_proposal_text")
        with self.conn:
            cur = self.conn.execute(
                "UPDATE persona_proposals SET new_text=?,diff=?,updated_at=? "
                "WHERE subject_key=? AND id=? AND status='pending'",
                (new_text, encoded, _now(), subject_key, proposal_id),
            )
        return cur.rowcount == 1
