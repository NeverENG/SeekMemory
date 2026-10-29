"""Narrow data ports consumed by the administration console."""
from typing import Any, Protocol


class PersonaPacks(Protocol):
    def catalog(self, collection: str, offset: int, limit: int) -> dict: ...
    def read(self, reference: str) -> dict: ...
    def save(self, seed: dict, expected_version: str | None = None) -> str: ...
    def remove(self, reference: str) -> None: ...


class DreamJournal(Protocol):
    def recent(self, limit: int = 7) -> list[dict]: ...


class DreamRunStore(DreamJournal, Protocol):
    """Read and record daily runs; callers own lifecycle and failure recovery.

    读取和记录每日整理；调用方管理生命周期及失败恢复。
    """

    def get(self, dream_date: str) -> dict[str, Any] | None:
        """Read one date, returning None when absent / 读取一天的记录，不存在返回空。"""
        ...

    def begin(self, dream_date: str, now: str = "") -> bool:
        """Start/resume unless already done; not a distributed lock / 未完成则开始或续跑，不提供分布式锁。"""
        ...

    def finish(self, dream_date: str, *, status: str = "done", batches: int = 0,
               written: int = 0, errors: list[str] | None = None,
               summary: dict[str, Any] | None = None, now: str = "") -> None:
        """Persist the outcome, raising on write failure / 保存结果，写入失败抛异常。"""
        ...
