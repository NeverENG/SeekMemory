"""不依赖宿主框架的 Artifact 检查、修订与召回诊断。"""

from __future__ import annotations

import dataclasses
import datetime
import json

try:
    from ..app.ports import Retriever
    from ..core.artifact import Artifact, content_of, revise, validate
    from ..core.graph import Graph
    from ..core.versioning import VersionError
    from ..recall.pipeline import Conf, build_block
    from ..recall.scope import owner_of, visible
    from ..store.cache import Cache
    from ..store.db import DB
except ImportError:
    from app.ports import Retriever
    from core.artifact import Artifact, content_of, revise, validate
    from core.graph import Graph
    from core.versioning import VersionError
    from recall.pipeline import Conf, build_block
    from recall.scope import owner_of, visible
    from store.cache import Cache
    from store.db import DB


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

    def __init__(self, db: DB, cache: Cache, graph: Graph, conf: Conf,
                 hybrid_retriever: Retriever | None = None) -> None:
        self.db, self.cache, self.graph, self.conf = db, cache, graph, conf
        self.hybrid_retriever = hybrid_retriever

    def catalog(self) -> list[dict]:
        """将所有 Artifact 家族转换为统一的记忆库契约。

        Returns:
            覆盖全部 scope 和非活跃状态的管理记录。
        """
        records = []
        for art in self.db.list():
            header, payload = art.header, art.payload
            text = content_of(art) or "（空内容）"
            versions = {}
            for version in self.db.history(header.id):
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
                    "session": owner_of(art, self.db.source_umo) or "未标注会话",
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
                        dict.fromkeys(edge[0] for edge in self.db.edges_of(header.id))
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
        art = self.db.get(node_id)
        if art is None:
            raise LookupError("记忆不存在")
        return {
            "artifact": dataclasses.asdict(art),
            **self.db.inspect_record(node_id),
            "ledger": [
                dict(row)
                for row in self.db.ledger_entries()
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
        art = self.db.get(body["id"])
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
            self.db.commit(
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
        owner = str(self.conf("owner_umo", ""))
        pool = self.cache.active()
        eligible = visible(pool, body["umo"], owner, self.db.source_umo)
        ids = {art.header.id for art in eligible}
        block, info = build_block(
            self.cache,
            self.graph,
            self.db,
            body["umo"],
            body["query"],
            ":FriendMessage:" in body["umo"],
            self.conf,
            owner,
            body["speaker"],
            dry_run=True,
            hybrid_retriever=self.hybrid_retriever,
        )
        return {
            "block": block,
            "info": info,
            "visible": sorted(ids),
            "excluded": [art.header.id for art in pool if art.header.id not in ids],
        }
