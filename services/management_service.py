"""不依赖宿主框架的 Artifact 检查、修订与召回诊断。"""

from __future__ import annotations

import dataclasses
import datetime
import json
import hashlib

try:
    from ..app.console_ports import PersonaPacks, DreamJournal
    from . import console_projection
    from ..app.ports import ArtifactCache, ArtifactStore, LedgerStore, SourceStore
    from ..core.artifact import Artifact, Lineage, Strength, content_of, make, revise, validate
    from ..core.bot_behavior import SELF_SUBJECT
    from ..core.persona import PERSONA_ORIGIN_SEED, persona_payload_from_file
    from ..core.versioning import VersionError
    from ..recall.scope import owner_of
    from .recall_service import RecallService
except ImportError:
    from app.console_ports import PersonaPacks, DreamJournal
    from services import console_projection
    from app.ports import ArtifactCache, ArtifactStore, LedgerStore, SourceStore
    from core.artifact import Artifact, Lineage, Strength, content_of, make, revise, validate
    from core.bot_behavior import SELF_SUBJECT
    from core.persona import PERSONA_ORIGIN_SEED, persona_payload_from_file
    from core.versioning import VersionError
    from recall.scope import owner_of
    from services.recall_service import RecallService


def timestamp(value: str) -> str:
    """将旧版本地时间规范化为前端可用的时间戳。

    Args:
        value: 后端存储的 ISO 日期或时间。

    Returns:
        带时区偏移的 ISO 时间戳；纪元时间表示未知的历史时间。
    """
    try:
        return datetime.datetime.fromisoformat(value).astimezone().isoformat()
    except ValueError:
        return "1970-01-01T00:00:00+00:00"


class ManagementService:
    """管理操作复用既有存储、缓存和 scope 规则。"""

    def __init__(self, artifacts: ArtifactStore, sources: SourceStore,
                 ledger: LedgerStore, cache: ArtifactCache,
                 recall_service: RecallService, *, packs: PersonaPacks | None = None,
                 dreams: DreamJournal | None = None) -> None:
        self.artifacts = artifacts
        self.sources = sources
        self.ledger = ledger
        self.cache = cache
        self.recall_service = recall_service
        self.packs = packs
        self.dreams = dreams

    def graph(self, limit: int = 120) -> dict:
        if type(limit) is not int or not 1 <= limit <= 120:
            raise ValueError("星图上限必须为 1–120")
        return console_projection.graph(self.artifacts, limit=limit)

    def impressions(self, offset: int = 0, limit: int = 100) -> dict:
        if not 0 <= offset <= 100000 or not 1 <= limit <= 100:
            raise ValueError("分页参数无效")
        return console_projection.impressions(self.artifacts, offset=offset, limit=limit)

    def dream_journal(self) -> dict:
        return console_projection.dreams(self.dreams.recent(100) if self.dreams else [])

    def pack_catalog(self, collection: str = "official", offset: int = 0) -> dict:
        if self.packs is None:
            raise RuntimeError("人格包目录不可用")
        return self.packs.catalog(collection, offset, 24)

    def pack_detail(self, reference: str) -> dict:
        if self.packs is None:
            raise RuntimeError("人格包目录不可用")
        bundle = self.packs.bundle(reference)
        return {"seed": bundle["seed"], "digest": self._pack_digest(bundle),
                "licenseText": bundle["licenseText"]}

    def pack_export(self, reference: str) -> dict:
        if self.packs is None:
            raise RuntimeError("人格包目录不可用")
        return self.packs.bundle(reference)

    def pack_artwork(self, reference: str) -> dict:
        if self.packs is None:
            raise RuntimeError("人格包目录不可用")
        return self.packs.artwork(reference)

    @staticmethod
    def _pack_digest(seed: dict) -> str:
        return hashlib.sha256(json.dumps(seed, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()

    def persona_action(self, body: dict) -> dict:
        if self.packs is None:
            raise RuntimeError("人格包目录不可用")
        if body.get("confirmed") is not True:
            raise ValueError("请先确认操作")
        operation = body.get("operation")
        fields = {
            "import": {"operation", "seed", "confirmed"},
            "importPack": {"operation", "pack", "confirmed"},
            "remove": {"operation", "reference", "confirmed"},
            "install": {"operation", "reference", "expectedId", "expectedRevision", "expectedDigest", "confirmed"},
        }
        if not isinstance(operation, str) or operation not in fields or set(body) - ({"expectedVersion"} if operation in {"import", "importPack"} else set()) != fields[operation]:
            raise ValueError("人格操作字段无效")

        reference = body.get("reference", "")
        if not isinstance(reference, str):
            raise ValueError("人格包标识无效")
        if operation in {"import", "importPack"}:
            expected = body.get("expectedVersion")
            if "expectedVersion" in body and not isinstance(expected, str):
                raise ValueError("人格包版本无效")
            return {"reference": self.packs.save(body.get("seed" if operation == "import" else "pack"), expected)}
        if operation == "remove":
            self.packs.remove(reference)
            return {"reference": reference}
        if operation != "install":
            raise ValueError("未知人格操作")
        current = sorted(self.cache.active("persona"), key=lambda art: (
            art.header.subject_id != SELF_SUBJECT, art.header.time.created, art.header.id))
        base = current[0] if current else None
        if (body.get("expectedId") != (base.header.id if base else None)
                or type(body.get("expectedRevision")) is not int
                or body["expectedRevision"] != (base.header.revision if base else 0)):
            raise ValueError("revision_conflict")
        bundle = self.packs.bundle(reference)
        if body.get("expectedDigest") != self._pack_digest(bundle):
            raise ValueError("pack_changed")
        return self.bootstrap_persona(bundle["seed"])

    def catalog(self) -> list[dict]:
        """将所有 Artifact 家族转换为统一的记忆库契约。

        Returns:
            覆盖全部 scope 和非活跃状态的管理记录。
        """
        records = []
        for art in self.artifacts.list():
            if art.header.family == "relationship":
                continue
            header, payload = art.header, art.payload
            text = content_of(art) or "（空内容）"
            versions = {}
            for version in self.artifacts.history(header.id):
                previous = Artifact(header=header, payload=version["payload"])
                versions[version["revision"]] = {
                    "revision": version["revision"],
                    "at": timestamp(version["at"]),
                    "text": content_of(previous) or "（空内容）",
                }
            versions[header.revision] = {
                "revision": header.revision,
                "at": timestamp(header.time.updated),
                "text": text,
            }
            category = (
                payload.get("level", "detail")
                if header.family == "memory"
                else header.family
            )
            tags = payload.get("tags", [])
            if isinstance(tags, str):
                tags = tags.split()
            records.append(
                {
                    "id": header.id,
                    "title": text[:60],
                    "text": text,
                    "category": category,
                    "state": header.state,
                    "scope": header.scope,
                    "subject": str(
                        header.subject_id
                        or payload.get("subject")
                        or header.said_by
                        or "未知对象"
                    ),
                    "session": owner_of(art, self.sources.source_umo) or "未标注会话",
                    "tags": [str(tag) for tag in tags if str(tag)]
                    if isinstance(tags, list)
                    else [],
                    "confidence": max(0, min(1, header.strength.confidence)),
                    "hits": max(0, header.strength.hits),
                    "updatedAt": timestamp(header.time.updated),
                    "versions": sorted(
                        versions.values(),
                        key=lambda item: item["revision"],
                        reverse=True,
                    ),
                    "relatedIds": list(
                        dict.fromkeys(edge[0] for edge in self.artifacts.edges_of(header.id))
                    ),
                }
            )
        return records

    def detail(self, node_id: str) -> dict:
        """检查原始正文、头部、证据、版本哈希和账本。

        Args:
            node_id: 待检查的 Artifact ID。

        Returns:
            管理详情，缺失的历史数据不补造。

        Raises:
            LookupError: Artifact 已不存在。
        """
        art = self.artifacts.get(node_id)
        if art is None:
            raise LookupError("记忆不存在")
        return {
            "artifact": dataclasses.asdict(art),
            **self.artifacts.inspect_record(node_id),
            "ledger": [
                dict(row)
                for row in self.ledger.entries()
                if row["entity"] == node_id
            ],
        }

    def update(self, body: dict) -> str:
        """校验并以原子事务修订 Artifact，随后刷新缓存。

        Args:
            body: 编辑命令，包含 ID、预期版本、正文、scope、状态和原因。

        Returns:
            修订后的 Artifact ID。

        Raises:
            ValueError: 输入无效或版本已过期。
            LookupError: Artifact 不存在。
        """
        if set(body) != {
            "id",
            "expectedRevision",
            "payload",
            "scope",
            "state",
            "reason",
            "confirmed",
        }:
            raise ValueError("编辑字段缺失或包含未支持的字段")
        if body["confirmed"] is not True:
            raise ValueError("请先确认操作")
        if type(body["expectedRevision"]) is not int or not isinstance(body["id"], str):
            raise ValueError("版本号或 ID 无效")
        valid_scope = body["scope"] in ("private", "shared", "shadow")
        valid_state = body["state"] in ("active", "forgotten", "merged")
        if not valid_scope or not valid_state:
            raise ValueError("状态或 scope 无效")
        if (
            not isinstance(body["reason"], str)
            or not 1 <= len(body["reason"].strip()) <= 300
        ):
            raise ValueError("请填写 1–300 个字符的修改原因")
        if (
            not isinstance(body["payload"], dict)
            or len(json.dumps(body["payload"])) > 50000
        ):
            raise ValueError("记忆内容必须为 JSON 对象，序列化后不超过 50,000 个字符")
        art = self.artifacts.get(body["id"])
        if art is None:
            raise LookupError("记忆不存在")
        if art.header.state == "merged" and body["state"] != "merged":
            raise ValueError("已合并的记忆不能独立恢复")
        if art.header.state != "merged" and body["state"] == "merged":
            raise ValueError("请通过维护任务合并记忆，以保留派生关系")
        replacement = revise(
            art, payload=body["payload"], scope=body["scope"], state=body["state"]
        )
        validate(replacement)
        try:
            self.artifacts.commit(
                replacement,
                expected_revision=body["expectedRevision"],
                op="forget" if body["state"] == "forgotten" else "revise",
                reason=body["reason"].strip(),
                source_ids=tuple(replacement.header.lineage.sources),
            )
        except VersionError as exc:
            raise ValueError("revision_conflict") from exc
        self.cache.put(replacement)
        return replacement.header.id

    def bootstrap_persona(self, seed_file: dict) -> dict:
        """Install one authored persona file as the initial persona revision.

        A persona file is authored configuration, not chat evidence.  It creates
        or revises the one active persona Artifact chain and never creates a
        Source or enters extraction/Dream.
        """
        payload = persona_payload_from_file(seed_file)
        active = sorted(self.cache.active("persona"), key=lambda art: (
            art.header.subject_id != SELF_SUBJECT,
            art.header.time.created,
            art.header.id,
        ))
        base = active[0] if active else None
        strength = Strength(confidence=1.0)
        common = dict(
            subject_id=SELF_SUBJECT,
            scope="shared",
            shareable="public",
            said_by=PERSONA_ORIGIN_SEED,
            state="active",
            strength=strength,
            lineage=Lineage(),
        )
        if base is None:
            persona = make("persona", payload, **common)
            expected = 0
        else:
            persona = revise(base, payload=payload, **common)
            expected = base.header.revision
        writes = [(persona, expected, ())]
        retired = [revise(art, state="merged") for art in active[1:]]
        writes.extend((art, art.header.revision - 1, ()) for art in retired)
        self.artifacts.commit_many(
            writes, op="promote", reason="persona seed bootstrap"
        )
        self.cache.put(persona)
        for art in retired:
            self.cache.remove(art.header.id)
        return {
            "id": persona.header.id,
            "revision": persona.header.revision,
            "seedId": str(payload["seed_id"]),
            "seedVersion": str(payload["seed_version"]),
        }

    def rollback_persona(self, body: dict) -> dict:
        """Restore a historical persona revision as a new active revision.

        Historical versions are never deleted.  Rollback creates a new revision
        on the same persona id so the audit chain remains append-only.
        """
        if set(body) != {"id", "revision", "reason", "confirmed"}:
            raise ValueError("回滚字段缺失或包含未支持的字段")
        if body["confirmed"] is not True:
            raise ValueError("请先确认操作")
        if not isinstance(body["id"], str) or type(body["revision"]) is not int:
            raise ValueError("ID 或 revision 无效")
        if body["revision"] < 1:
            raise ValueError("revision 必须大于 0")
        reason = body["reason"]
        if not isinstance(reason, str) or not 1 <= len(reason.strip()) <= 300:
            raise ValueError("请填写 1–300 个字符的回滚原因")
        current = self.artifacts.get(body["id"])
        if current is None:
            raise LookupError("记忆不存在")
        if current.header.family != "persona":
            raise ValueError("只能回滚 persona")
        if current.header.state != "active":
            raise ValueError("只能回滚 active persona")
        target = next(
            (row for row in self.artifacts.history(current.header.id)
             if int(row.get("revision") or 0) == body["revision"]),
            None,
        )
        if target is None or not isinstance(target.get("payload"), dict):
            raise ValueError("目标 persona revision 不存在")
        if target["revision"] == current.header.revision:
            raise ValueError("目标 revision 已经是当前版本")
        snapshot = self._persona_version_header(current.header.id, target["revision"])
        raw_lineage = self._json_object(snapshot.get("lineage"))
        lineage = Lineage(
            sources=tuple(str(value) for value in raw_lineage.get("sources", ()) if value),
            derived_from=tuple(
                str(value) for value in raw_lineage.get("derived_from", ()) if value
            ),
        )
        raw_strength = self._json_object(snapshot.get("strength"))
        strength = Strength(
            **{
                field.name: raw_strength[field.name]
                for field in dataclasses.fields(Strength)
                if field.name in raw_strength
            }
        )
        payload = dict(target["payload"])
        said_by = "seed" if payload.get("origin") == PERSONA_ORIGIN_SEED else "inferred"
        replacement = revise(
            current,
            payload=payload,
            state="active",
            scope=str(snapshot.get("scope") or "shared"),
            subject_id=str(snapshot.get("subject_id") or SELF_SUBJECT),
            said_by=said_by,
            shareable="public",
            lineage=lineage,
            strength=strength,
        )
        validate(replacement)
        self.artifacts.commit(
            replacement,
            expected_revision=current.header.revision,
            op="revise",
            reason=reason.strip(),
            source_ids=tuple(lineage.sources),
        )
        self.cache.put(replacement)
        return {
            "id": replacement.header.id,
            "revision": replacement.header.revision,
            "restoredRevision": target["revision"],
        }

    @staticmethod
    def _json_object(raw: object) -> dict:
        value = raw
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (TypeError, ValueError):
                return {}
        return value if isinstance(value, dict) else {}

    def _persona_version_header(self, node_id: str, revision: int) -> dict:
        record = self.artifacts.inspect_record(node_id)
        for row in record.get("versions", []):
            try:
                if int(row.get("revision") or 0) == revision:
                    return self._json_object(row.get("header"))
            except (TypeError, ValueError):
                continue
        raise ValueError("目标 persona revision 的 header 不存在")

    def diagnose(self, body: dict) -> dict:
        """按实际规则预演召回，不消耗指定交付状态。

        Args:
            body: 查询文本、完整会话 UMO 和发送者身份。

        Returns:
            注入文本、决策计数，以及 scope 候选和排除 ID。

        Raises:
            ValueError: 诊断输入缺失或超出长度限制。
        """
        for key, maximum in (("query", 4000), ("umo", 500), ("speaker", 200)):
            if (
                not isinstance(body.get(key), str)
                or not 0 < len(body[key].strip()) <= maximum
            ):
                raise ValueError(f"字段 {key} 无效")
        private = ":FriendMessage:" in body["umo"]
        return self.recall_service.preview(
            body["query"], body["umo"], private, body["speaker"]
        )
