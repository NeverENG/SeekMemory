"""Read management status; no Source text, writes or owned resources.

读取管理状态，不读取原始消息正文、执行写入或拥有资源。
"""

from __future__ import annotations

import json
try:
    from ..app.value_codec import json_object
except ImportError:
    from app.value_codec import json_object

try:
    from ..app.ports import ArtifactStore, LedgerStore
except ImportError:
    from app.ports import ArtifactStore, LedgerStore


class StatusService:
    """Read persona versions and ledger integrity without Source text / 读取人格版本及账本完整性，不读取原始消息正文。"""

    def __init__(self, *, artifacts: ArtifactStore | None,
                 ledger: LedgerStore | None = None) -> None:
        self.artifacts = artifacts
        self.ledger = ledger

    json_object = staticmethod(json_object)

    @classmethod
    def header_evidence(cls, raw_header: object) -> tuple[list[str], list[str]]:
        """Read source and derived-memory IDs from legacy version headers / 从旧版本头部读取原始消息及派生记忆编号。"""
        header = cls.json_object(raw_header)
        lineage = cls.json_object(header.get("lineage"))

        def ids(*names: str) -> list[str]:
            """Normalize supplied evidence references for the management view.

            为管理视图整理给定证据引用。
            """
            for name in names:
                value = lineage.get(name)
                if isinstance(value, str):
                    try:
                        value = json.loads(value)
                    except (TypeError, ValueError):
                        continue
                if not isinstance(value, (list, tuple)):
                    continue
                out: list[str] = []
                for item in value:
                    if not isinstance(item, str):
                        continue
                    text = item.strip()
                    if text and text not in out:
                        out.append(text)
                return out
            return []

        return ids("derived_from", "derivedFrom"), ids("sources", "sourceIds")

    def persona(self) -> dict | None:
        """Read the current persona with each versions own evidence / 读取当前人格及各版本自身的证据。"""
        if self.artifacts is None:
            return None
        active = [art for art in self.artifacts.list(family="persona", state="active")]
        if not active:
            return None
        current = max(active, key=lambda art: art.header.revision)
        evidence: dict[int, tuple[list[str], list[str]]] = {}
        inspected = self.artifacts.inspect_record(current.header.id)
        for row in inspected.get("versions", []):
            try:
                revision = int(row.get("revision") or 0)
            except (TypeError, ValueError):
                continue
            evidence[revision] = self.header_evidence(row.get("header"))
        revisions = []
        for row in self.artifacts.history(current.header.id):
            revision = int(row.get("revision") or 0)
            derived_from, source_ids = evidence.get(revision, ([], []))
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            revisions.append({
                "revision": revision,
                "at": str(row.get("at") or ""),
                "op": str(row.get("op") or ""),
                "text": str(payload.get("text") or ""),
                "origin": str(payload.get("origin") or ""),
                "synthesis": str(payload.get("synthesis") or ""),
                "changeReason": str(payload.get("change_reason") or ""),
                "derivedFrom": list(derived_from),
                "sourceIds": list(source_ids),
            })
        return {
            "id": current.header.id,
            "revision": int(current.header.revision),
            "text": str(current.payload.get("text") or ""),
            "origin": str(current.payload.get("origin") or ""),
            "synthesis": str(current.payload.get("synthesis") or ""),
            "changeReason": str(current.payload.get("change_reason") or ""),
            "seedId": str(current.payload.get("seed_id") or ""),
            "seedVersion": str(current.payload.get("seed_version") or ""),
            "corpusCount": int(
                current.payload.get("corpus_count")
                or len(current.payload.get("corpus") or [])
            ),
            "revisions": revisions,
        }

    def ledger_valid(self) -> bool:
        """Verify the stored append-only ledger chain / 验证已保存的追加式账本链。"""
        return bool(self.ledger is not None and self.ledger.verify())
