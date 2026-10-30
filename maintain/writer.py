"""Own prepared maintenance persistence and cache-only repair in this process.

管理当前进程中已准备的维护持久化及仅需缓存的补偿；资源由组装方管理。
"""
from __future__ import annotations

from dataclasses import dataclass

try:
    from ..core.domain.memory.versioning import VersionError
    from ..app.cache_repair import CacheRepairs
except ImportError:
    from core.domain.memory.versioning import VersionError
    from app.cache_repair import CacheRepairs
from .plans import RevisionPlan
from .ports import ArtifactStore, ArtifactCache


@dataclass(frozen=True)
class _PreparedWrite:
    """One exact group or single commit, never automatically rebased.

    一个精确的分组或单次提交，不自动基于新版本重算。
    """

    plan: RevisionPlan
    grouped: bool


class MaintenanceWriter:
    """Retain unfinished plans and repair latest cache heads after durable commits.

    保留未完成计划，在持久提交后补偿最新缓存版本；不创建模型或提供崩溃恢复保证。
    """

    def __init__(self, artifacts: ArtifactStore, cache: ArtifactCache | None,
                 *, defer_cache_errors: bool = False,
                 cache_repairs: CacheRepairs | None = None) -> None:
        self.artifacts = artifacts
        self.cache = cache
        self.defer_cache_errors = defer_cache_errors
        self._pending: dict[tuple, _PreparedWrite] = {}
        self.cache_repairs = cache_repairs or CacheRepairs(artifacts, cache)
        self._retrying = False
        self.committed = 0

    def pending(self) -> int:
        """Count distinct IDs awaiting a commit or cache repair / 按编号去重统计待提交或待缓存补偿的项。"""
        ids = {write.artifact.header.id for item in self._pending.values() for write in item.plan.writes}
        return len(ids | self.cache_repairs.ids(self))

    def execute(self, plan: RevisionPlan, *, grouped: bool = True) -> int:
        """Commit the exact plan, then repair cache; return newly committed memories.

        提交精确计划，再补偿缓存，返回新增提交的记忆数；分组原子性与单次提交明确区分。
        """
        if not plan.writes:
            return 0
        key = (plan.op, plan.reason, tuple((write.artifact.header.id, write.expected_revision)
                                          for write in plan.writes))
        self._pending.setdefault(key, _PreparedWrite(plan, grouped))
        committed = self._commit(key)
        self._repair()
        return committed

    def _commit(self, key: tuple) -> int:
        """Consume a plan immediately after database success; conflicts never rebase.

        数据库成功后立即消费计划，冲突时不基于新版本重放。
        """
        prepared = self._pending[key]
        plan = prepared.plan
        try:
            if prepared.grouped:
                self.artifacts.commit_many(plan.rows(), op=plan.op, reason=plan.reason)
            else:
                if len(plan.writes) != 1:
                    raise ValueError("single maintenance commit requires one revision")
                write = plan.writes[0]
                self.artifacts.commit(
                    write.artifact, expected_revision=write.expected_revision, op=plan.op,
                    reason=plan.reason, source_ids=write.source_ids,
                )
        except VersionError:
            self._pending.pop(key, None)
            raise
        self._pending.pop(key, None)
        for write in plan.writes:
            self.cache_repairs.mark(write.artifact.header.id, self)
        self.committed += len(plan.writes)
        return len(plan.writes)

    def _repair(self) -> None:
        """Repair from latest database heads; failures retain their IDs.

        从数据库最新版本补偿，失败时保留编号；不发布旧计划中的快照。
        """
        self.cache_repairs.artifacts = self.artifacts
        self.cache_repairs.cache = self.cache
        failure: Exception | None = None
        for entity in tuple(self.cache_repairs.ids(self)):
            try:
                self.cache_repairs.repair(entity)
            except Exception as exc:
                failure = failure or exc
        if failure is not None and not self.defer_cache_errors:
            raise failure

    def retry_writebacks(self) -> int:
        """Resume exact prepared writes without policy/model calls; return completed IDs.

        不调用规则或模型，仅恢复精确的已准备写入，返回完成编号数。
        """
        if self._retrying:
            return 0
        self._retrying = True
        before = self.pending()
        try:
            for key in tuple(self._pending):
                try:
                    self._commit(key)
                except Exception:
                    continue
            try:
                self._repair()
            except Exception:
                pass
        finally:
            self._retrying = False
        return max(0, before - self.pending())

    def ensure_ready(self) -> None:
        """Finish prior work before deriving new plans from the cache.

        在根据缓存推导新计划前完成旧工作，避免旧视图导致重复生成记忆。
        """
        self.retry_writebacks()
        self.cache_repairs.retry()
        if self.pending() or self.cache_repairs.ids():
            raise RuntimeError("maintenance_writeback_pending")
