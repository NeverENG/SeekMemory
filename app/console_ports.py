"""Console and daily-journal declarations; implementations and resources remain external / 控制台及每日台账声明，实现及资源留在外部。"""
from typing import Any, Protocol


class PersonaPacks(Protocol):
    """Console access to seed packs; storage and lifecycle belong to the caller / 控制台人格包能力，存储和生命周期由调用方管理。"""
    def catalog(self, collection: str, offset: int, limit: int) -> dict:
        """Read a bounded catalogue page / 读取有数量限制的目录页。"""
        ...
    def read(self, reference: str) -> dict:
        """Read one referenced pack / 读取指定人格包。"""
        ...
    def save(self, seed: dict, expected_version: str | None = None) -> str:
        """Save with an optional expected version and return its reference / 可指定预期版本保存，并返回引用。"""
        ...
    def remove(self, reference: str) -> None:
        """Remove the referenced pack / 删除指定人格包。"""
        ...


class DreamJournal(Protocol):
    """Read-only console view of recent daily runs / 控制台使用的近期每日整理只读视图。"""
    def recent(self, limit: int = 7) -> list[dict]:
        """Read a bounded list of recent runs / 读取有数量限制的近期整理记录。"""
        ...


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
