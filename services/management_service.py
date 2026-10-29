"""Expose compatible management entries; delegate queries and explicit commands.

提供兼容的管理入口，分别委托查询与明确的修改命令；连接、缓存及人格包由组装方管理。
"""
from __future__ import annotations

try:
    from ..app.ports import ArtifactCache, ArtifactStore, LedgerStore, SourceStore, PersonaPacks, DreamJournal
except ImportError:
    from app.ports import ArtifactCache, ArtifactStore, LedgerStore, SourceStore, PersonaPacks, DreamJournal

from . import management_queries as queries, management_commands as commands
from .management_queries import timestamp
from .recall_service import RecallService


class ManagementService:
    """Coordinate management reads and writes without owning resources.

    协调管理读写，不拥有资源；数据库提交后缓存失败会向调用方报告。
    """

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
        """Read a bounded graph projection / 读取有数量上限的图视图。"""
        return queries.graph(self.artifacts, limit)

    def impressions(self, offset: int = 0, limit: int = 100) -> dict:
        """Read one impression page / 读取一页印象。"""
        return queries.impressions(self.artifacts, offset, limit)

    def dream_journal(self) -> dict:
        """Read recent dream runs / 读取近期夜间整理记录。"""
        return queries.dream_journal(self.dreams)

    def pack_catalog(self, collection: str = "official", offset: int = 0) -> dict:
        """Read a persona pack catalog page / 读取一页人格包目录。"""
        return queries.pack_catalog(self.packs, collection, offset)

    def pack_detail(self, reference: str) -> dict:
        """Read a pack and its confirmation digest / 读取人格包及其确认摘要。"""
        return queries.pack_detail(self.packs, reference)

    def pack_export(self, reference: str) -> dict:
        """Read the complete authored pack / 读取完整的人工编写人格包。"""
        return queries.pack_export(self.packs, reference)

    def pack_artwork(self, reference: str) -> dict:
        """Read validated artwork metadata / 读取已验证的插画元数据。"""
        return queries.pack_artwork(self.packs, reference)

    def catalog(self) -> list[dict]:
        """Read management records including inactive memories / 读取含非有效记忆的管理记录。"""
        return queries.catalog(self.artifacts, self.sources)

    def detail(self, node_id: str) -> dict:
        """Read memory, evidence, versions and ledger; absence raises / 读取记忆、证据、版本与账本，不存在时抛错。"""
        return queries.detail(self.artifacts, self.ledger, node_id)

    def update(self, body: dict) -> str:
        """Validate and commit a memory edit using its expected revision / 校验并按预期版本提交记忆修改。"""
        return commands.update(self.artifacts, self.cache, body)

    def bootstrap_persona(self, seed_file: dict) -> dict:
        """Commit an authored persona seed without creating Source / 提交人工人格设定，不创建原始消息。"""
        return commands.bootstrap_persona(self.artifacts, self.cache, seed_file)

    def rollback_persona(self, body: dict) -> dict:
        """Restore historical persona content as a new audited revision / 将历史人格内容恢复为可审计的新版本。"""
        return commands.rollback_persona(self.artifacts, self.cache, body)

    def persona_action(self, body: dict) -> dict:
        """Validate and execute one confirmed pack operation / 校验并执行一次已确认的人格包操作。"""
        return commands.persona_action(self.artifacts, self.cache, self.packs, body)

    def _persona_version_header(self, node_id: str, revision: int) -> dict:
        """Read an existing historical persona header / 读取已存在的历史人格头部。"""
        return queries._persona_version_header(self.artifacts, node_id, revision)

    _pack_digest = staticmethod(queries.pack_digest)
    _json_object = staticmethod(queries.json_object)

    def diagnose(self, body: dict) -> dict:
        """Validate diagnostic input and preview recall without consuming designated memory / 验证诊断输入并预览召回，不消耗指定记忆。"""
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
