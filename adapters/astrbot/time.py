"""Apply the existing UTC+8 hook at host write/read edges; never rewrite historical Source.

在宿主写读适配处应用既有 UTC+8 钩子，不改写历史原始消息。
"""

from __future__ import annotations

import datetime
from dataclasses import replace
from typing import Any, Callable

try:
    from ...app.contracts import DialogueTurn
    from ...app.ports import SourceStore
    from ...app.runtime.recorder import RecordedReply, RecordedTurn, RunRecorder
    from ...core.source import Source
    from ...perceive.buffer import Buffer
except ImportError:  # Top-level adapter imports / 顶层适配器导入。 in scripts/tests
    from app.contracts import DialogueTurn
    from app.ports import SourceStore
    from app.runtime.recorder import RecordedReply, RecordedTurn, RunRecorder
    from core.source import Source
    from perceive.buffer import Buffer

UTC8 = datetime.timezone(datetime.timedelta(hours=8))


def utc8_time_hook(
    at: str = "",
    *,
    now: bool = False,
    projection: bool = False,
    clock: Callable[[], float] | None = None,
) -> str:
    """Convert known instants to UTC+8; preserve naive/invalid legacy values and existing projection shape / 将已知时刻转换为 UTC+8，保留无时区或无效旧值及既有视图形式。"""
    if not at:
        if not now:
            return at
        if clock is None:
            raise ValueError("clock is required when now=True")
        value = datetime.datetime.fromtimestamp(float(clock()), UTC8)
    else:
        try:
            value = datetime.datetime.fromisoformat(at.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return at
        if value.tzinfo is None:
            return at
    value = value.astimezone(UTC8)
    if projection:
        value = value.replace(tzinfo=None)
    return value.isoformat(timespec="seconds")


def utc8_timestamp(at: str) -> float:
    """Return a known UTC+8 instant or zero for unknown legacy timezone / 返回已知 UTC+8 时刻，未知旧时区返回零。"""
    try:
        value = datetime.datetime.fromisoformat(utc8_time_hook(at))
        return value.timestamp() if value.tzinfo is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


class AstrBotSourceView:
    """Normalize evidence read views without rewriting immutable Sources / 规范化证据读取视图，不改写不可变原始消息。"""

    def __init__(self, sources: SourceStore) -> None:
        self.sources = sources

    def append_sources(self, sources: list[Source]) -> int:
        """Delegate unchanged immutable evidence append / 委托不变的不可变证据追加。"""
        return self.sources.append_sources(sources)

    def recent_sources(self, *, since: str, limit: int) -> list[Source]:
        """Read bounded evidence and normalize only its view timestamp / 限量读取证据，仅规范化其视图时间戳。"""
        return [
            replace(source, at=utc8_time_hook(source.at, projection=True))
            for source in self.sources.recent_sources(since=since, limit=limit)
        ]

    def source_umo(self, source_id: str) -> str:
        """Delegate source-session lookup / 委托原始消息来源会话查询。"""
        return self.sources.source_umo(source_id)

    def source_umos(self, source_ids: list[str]) -> dict[str, str]:
        """Delegate batched source-session lookup / 委托批量原始消息来源会话查询。"""
        return self.sources.source_umos(source_ids)

    def sources_by_ids(self, source_ids: list[str]) -> dict[str, Source]:
        """Read evidence by ID and normalize view timestamps only / 按编号读取证据，仅规范化视图时间戳。"""
        return {
            key: replace(source, at=utc8_time_hook(source.at, projection=True))
            for key, source in self.sources.sources_by_ids(source_ids).items()
        }


class AstrBotRunRecorder(RunRecorder):
    """Apply the existing time hook before delegating every existing write path / 在委托所有既有写入路径前应用现有时间钩子。"""

    def __init__(self, *args, clock: Callable[[], float] | None = None, **kwargs) -> None:
        self.host_clock = clock or (lambda: 0.0)
        super().__init__(*args, clock=clock, **kwargs)

    def record_user(self, *, at: str = "", **fields: Any) -> RecordedTurn:
        """Convert the host timestamp then delegate immutable user capture / 转换宿主时间戳后委托不可变用户捕获。"""
        return super().record_user(
            at=utc8_time_hook(at, now=True, clock=self.host_clock), **fields
        )

    def record_reply(self, *, at: str = "", **fields: Any) -> RecordedReply:
        """Convert the host timestamp then delegate immutable reply capture / 转换宿主时间戳后委托不可变回复捕获。"""
        return super().record_reply(
            at=utc8_time_hook(at, now=True, clock=self.host_clock), **fields
        )

    def record_delivery(self, *, at: str = "", **fields: Any) -> None:
        """Convert the host timestamp then delegate confirmed-delivery audit / 转换宿主时间戳后委托已确认交付审计。"""
        super().record_delivery(
            at=utc8_time_hook(at, now=True, clock=self.host_clock), **fields
        )

    def record_error(self, *, at: str = "", **fields: Any) -> None:
        """Convert the host timestamp then delegate the existing error audit / 转换宿主时间戳后委托既有错误审计。"""
        super().record_error(
            at=utc8_time_hook(at, now=True, clock=self.host_clock), **fields
        )


class AstrBotBuffer(Buffer):
    """Apply existing UTC+8 views and age signals over the base queue behavior / 在基础队列行为之上应用既有 UTC+8 视图及年龄信号。"""

    def __init__(
        self, path: str = "", extraction=None, clock: Callable[[], float] | None = None
    ) -> None:
        self._source_times: dict[str, float] = {}
        self.clock = clock or (lambda: 0.0)
        super().__init__(path, extraction=extraction)

    @staticmethod
    def _view(turn: DialogueTurn) -> DialogueTurn:
        """Apply the existing UTC+8 naive projection to one turn / 对一个轮次应用既有 UTC+8 无时区视图。"""
        return replace(turn, at=utc8_time_hook(turn.at, projection=True))

    def add(
        self, umo: str, text: str, sender: str = "", source_id: str = "",
        at: str = "", *, source: Source | None = None, **fields: Any,
    ) -> DialogueTurn | None:
        """Delegate queue admission then normalize the existing time view / 委托队列接纳后规范化既有时间视图。"""
        at = utc8_time_hook(
            at or (source.at if source is not None else ""),
            now=True,
            clock=self.clock,
        )
        turn = super().add(
            umo, text, sender, source_id, at,
            source=source, **fields,
        )
        if turn is not None:
            stamp = utc8_timestamp(at)
            if stamp and turn.source_id:
                self._source_times[turn.source_id] = stamp
            self.items = [self._view(item) for item in self.items]
            self._timestamps()
            return self._view(turn)
        return None

    def _topic_for(
        self, turn: DialogueTurn, previous: DialogueTurn | None,
        parent: DialogueTurn | None = None,
    ) -> str:
        """Pass existing normalized time views to the unchanged topic rule / 将既有规范时间视图传给不变话题规则。"""
        return super()._topic_for(
            self._view(turn),
            self._view(previous) if previous is not None else None,
            self._view(parent) if parent is not None else None,
        )

    def _load_projection(self) -> None:
        """Read the existing queue, then apply its UTC+8 view and known-instant map / 读取既有队列，再应用 UTC+8 视图及已知时刻映射。"""
        super()._load_projection()
        self._source_times = {
            turn.source_id: utc8_timestamp(turn.at) for turn in self.items
            if turn.source_id
        }
        self.items = [self._view(turn) for turn in self.items]
        self.last_ts = max(self._timestamps(), default=0.0)

    def _timestamps(self) -> list[float]:
        """Keep known instants only for currently pending Source IDs / 仅为当前待处理原始消息编号保留已知时刻。"""
        pending_ids = {turn.source_id for turn in self.items}
        self._source_times = {
            key: stamp for key, stamp in self._source_times.items() if key in pending_ids
        }
        return [stamp for stamp in self._source_times.values() if stamp]

    def oldest_topic_age(self) -> float:
        """Compute existing age from known instants and the supplied clock / 按已知时刻及给定时钟计算既有年龄。"""
        stamps = self._timestamps()
        return max(0.0, self.clock() - min(stamps)) if stamps else 0.0
