"""Read management projections through injected repositories; never write memory.

通过注入的仓储读取管理视图，不写入记忆；资源生命周期由调用方管理。
"""
from __future__ import annotations

import dataclasses
import datetime
import hashlib
import json

try:
    from ..app.ports import ArtifactStore, SourceStore, LedgerStore, PersonaPacks, DreamJournal
    from ..core.artifact import Artifact, content_of
    from ..recall.scope import owner_of
except ImportError:
    from app.ports import ArtifactStore, SourceStore, LedgerStore, PersonaPacks, DreamJournal
    from core.artifact import Artifact, content_of
    from recall.scope import owner_of

from . import console_projection

def timestamp(value: str) -> str:
    """Format stored dates using the existing local-zone conversion and epoch fallback / 沿用现有本地时区转换及纪元回退来格式化已存日期。"""
    try:
        return datetime.datetime.fromisoformat(value).astimezone().isoformat()
    except ValueError:
        return "1970-01-01T00:00:00+00:00"


def graph(artifacts: ArtifactStore, limit: int = 120) -> dict:
    """Read a bounded graph projection without Source bodies / 读取有数量上限且不含原始消息正文的图视图。"""
    if type(limit) is not int or not 1 <= limit <= 120:
        raise ValueError("星图上限必须为 1–120")
    return console_projection.graph(artifacts, limit=limit)


def impressions(artifacts: ArtifactStore, offset: int = 0, limit: int = 100) -> dict:
    """Read one bounded management impression page / 读取一页有数量上限的管理印象。"""
    if not 0 <= offset <= 100000 or not 1 <= limit <= 100:
        raise ValueError("分页参数无效")
    return console_projection.impressions(artifacts, offset=offset, limit=limit)


def dream_journal(dreams: DreamJournal | None) -> dict:
    """Read the most recent bounded dream-run projection / 读取近期有数量上限的夜间整理记录视图。"""
    return console_projection.dreams(dreams.recent(100) if dreams else [])


def pack_catalog(packs: PersonaPacks | None, collection: str = "official", offset: int = 0) -> dict:
    """Read a bounded pack catalog page; unavailable storage raises / 读取一页有数量上限的人格包目录，存储不可用时抛错。"""
    if packs is None:
        raise RuntimeError("人格包目录不可用")
    return packs.catalog(collection, offset, 24)


def pack_detail(packs: PersonaPacks | None, reference: str) -> dict:
    """Read the seed, license and digest for pack confirmation / 读取用于人格包确认的设定、许可证及摘要。"""
    if packs is None:
        raise RuntimeError("人格包目录不可用")
    bundle = packs.bundle(reference)
    return {"seed": bundle["seed"], "digest": pack_digest(bundle),
            "licenseText": bundle["licenseText"]}


def pack_export(packs: PersonaPacks | None, reference: str) -> dict:
    """Read a complete authored pack bundle / 读取完整的人工编写人格包。"""
    if packs is None:
        raise RuntimeError("人格包目录不可用")
    return packs.bundle(reference)


def pack_artwork(packs: PersonaPacks | None, reference: str) -> dict:
    """Read validated persona artwork metadata / 读取已验证的人格插画元数据。"""
    if packs is None:
        raise RuntimeError("人格包目录不可用")
    return packs.artwork(reference)


def catalog(artifacts: ArtifactStore, sources: SourceStore) -> list[dict]:
    """Read all management memories and their versions, excluding relationship records / 读取管理记忆及其版本，排除关系记录。"""
    records = []
    for art in artifacts.list():
        if art.header.family == "relationship":
            continue
        header, payload = art.header, art.payload
        text = content_of(art) or "（空内容）"
        versions = {}
        for version in artifacts.history(header.id):
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
                "session": owner_of(art, sources.source_umo) or "未标注会话",
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
                    dict.fromkeys(edge[0] for edge in artifacts.edges_of(header.id))
                ),
            }
        )
    return records


def detail(artifacts: ArtifactStore, ledger: LedgerStore, node_id: str) -> dict:
    """Read a memory, its evidence, versions and ledger; absence raises LookupError / 读取记忆、证据、版本及账本，不存在时抛出 LookupError。"""
    art = artifacts.get(node_id)
    if art is None:
        raise LookupError("记忆不存在")
    return {
        "artifact": dataclasses.asdict(art),
        **artifacts.inspect_record(node_id),
        "ledger": [
            dict(row)
            for row in ledger.entries()
            if row["entity"] == node_id
        ],
    }


def _persona_version_header(artifacts: ArtifactStore, node_id: str, revision: int) -> dict:
    """Read an existing historical persona header; absence raises / 读取已存在的历史人格头部，不存在时抛错。"""
    record = artifacts.inspect_record(node_id)
    for row in record.get("versions", []):
        try:
            if int(row.get("revision") or 0) == revision:
                return json_object(row.get("header"))
        except (TypeError, ValueError):
            continue
    raise ValueError("目标 persona revision 的 header 不存在")


def pack_digest(seed: dict) -> str:
    """Compute a canonical content digest without writing files / 计算规范化内容摘要，不写入文件。"""
    return hashlib.sha256(json.dumps(seed, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode("utf-8")).hexdigest()


def json_object(raw: object) -> dict:
    """Decode an object or return an empty object for invalid legacy data / 解析对象，对无效的旧数据返回空对象。"""
    value = raw
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}
