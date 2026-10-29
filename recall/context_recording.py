"""Explicit context-inclusion writer and process-local unfinished-stage owner.

明确的上下文包含写入及进程内未完成阶段所有者，与纯查询分开；资源由组装方管理。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

try:
    from ..app.ports import ArtifactStore, ArtifactCache
    from ..app.cache_repair import CacheRepairs
    from ..core.artifact import Artifact, revise
    from ..core.versioning import VersionError
except ImportError:
    from app.ports import ArtifactStore, ArtifactCache
    from app.cache_repair import CacheRepairs
    from core.artifact import Artifact, revise
    from core.versioning import VersionError
from .designated_policy import already_given


@dataclass(frozen=True)
class _Inclusion:
    """One observed revision and actual included block / 一个观察到的版本及实际包含的文本块。"""

    revision: int
    block: str
    at: str


class ContextRecorder:
    """Own pending inclusion commits and cache-only repairs, never model/send retries.

    管理待提交包含记录及仅需缓存补偿的工作，不负责模型或发送重试；突然退出不保证补偿。
    """

    def __init__(self, artifacts: ArtifactStore, cache: ArtifactCache | None,
                 *, cache_repairs: CacheRepairs | None = None) -> None:
        self.artifacts = artifacts
        self.cache = cache
        self._pending: dict[str, _Inclusion] = {}
        self.cache_repairs = cache_repairs or CacheRepairs(artifacts, cache)
        self._retrying = False

    def record(self, block: str, info: dict, now: str | None = None) -> int:
        """Remember exact included revisions; return newly committed markers.

        记住实际包含的精确版本，返回新增提交的标记数；缓存失败不将提交重新分类为失败。
        """
        if not block or self.artifacts is None:
            return 0
        final_ids = set(info.get("final_ids", ()))
        revisions = dict(info.get("designated_revisions", ()))
        stamp = now or datetime.now().isoformat(timespec="seconds")
        for entity in dict.fromkeys(info.get("designated_ids", ())):
            if entity not in final_ids:
                continue
            revision = revisions.get(entity)
            if revision is None:
                try:
                    current = self.artifacts.get(entity)
                except Exception:
                    continue
                if current is None:
                    continue
                revision = current.header.revision
            self._pending.setdefault(entity, _Inclusion(int(revision), block, stamp))
        return self._retry()

    def record_artifacts(self, arts: list[Artifact], block: str, now: str | None = None) -> int:
        """Keep the legacy body-checking entry without a second write implementation.

        保留旧正文检查入口，不另行实现一套写入流程。
        """
        designated = [art for art in arts if art.header.family == "designated"]
        return self.record(block, {
            "final_ids": tuple(art.header.id for art in designated),
            "designated_ids": tuple(art.header.id for art in designated),
            "designated_revisions": tuple((art.header.id, art.header.revision) for art in designated),
        }, now)

    def _repair(self, entity: str) -> None:
        """Read the latest head before cache refresh; failures retain ownership.

        缓存刷新前读取最新版本，失败时保留工作归属，不发布旧快照。
        """
        self.cache_repairs.repair(entity)

    def _retry(self) -> int:
        """Resume unfinished persistence; never rebase a conflicting inclusion onto new text.

        恢复未完成持久化，发生冲突时绝不将旧包含记录重放到新正文。
        """
        if self._retrying:
            return 0
        self._retrying = True
        committed = 0
        try:
            for entity, inclusion in tuple(self._pending.items()):
                try:
                    current = self.artifacts.get(entity)
                    if current is None or current.header.family != "designated":
                        self._pending.pop(entity, None)
                        continue
                    if already_given(current):
                        self._pending.pop(entity, None)
                        self.cache_repairs.mark(entity, self)
                        continue
                    if current.header.revision != inclusion.revision:
                        self._pending.pop(entity, None)
                        continue
                    body = " ".join(str(current.payload.get("text") or "").split())[:24]
                    if not body or body not in inclusion.block:
                        self._pending.pop(entity, None)
                        continue
                    updated = revise(current, payload={**current.payload, "given": inclusion.at})
                    self.artifacts.commit(
                        updated, expected_revision=current.header.revision, op="deliver",
                        reason="designated delivered", source_ids=tuple(current.header.lineage.sources),
                    )
                except VersionError:
                    self._pending.pop(entity, None)
                    continue
                except Exception:
                    continue
                # Durability is final before any fallible cache operation.
                # 在任何可能失败的缓存操作之前，持久提交已确认为完成。
                self._pending.pop(entity, None)
                self.cache_repairs.mark(entity, self)
                committed += 1
            for entity in tuple(self.cache_repairs.ids(self)):
                try:
                    self._repair(entity)
                except Exception:
                    continue
        finally:
            self._retrying = False
        return committed

    def retry_writebacks(self) -> int:
        """Return distinct completed operations without model calls or queries.

        返回完成的不同操作数量，不调用模型或召回查询。
        """
        before = set(self._pending) | set(self.cache_repairs.ids(self))
        self._retry()
        return len(before - (set(self._pending) | set(self.cache_repairs.ids(self))))


def record_context(artifacts: ArtifactStore, cache: ArtifactCache,
                   block: str, info: dict) -> int:
    """Attempt explicit recording once; services retain a recorder for compensation.

    明确尝试一次记录，服务持有记录器以便后续补偿；模型及发送结果不参与判断。
    """
    return ContextRecorder(artifacts, cache).record(block, info)
