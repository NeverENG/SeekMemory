"""Freeze wall-clock reads for the duration of a benchmark run, then restore them.

在一次评测运行期间冻结真实时钟读取，结束后恢复；只替换被评测路径实际读取的符号。

Production code reads ``datetime.date.today()`` in maintenance/decay/supersede and
``datetime`` / ``date`` in recall scoring, plus ``core.artifact._now`` / ``_new_id``
for identity.  A fake clock has to reach exactly those symbols: patching the real
``datetime`` module is not possible, and patching more than needed would hide real
dependencies.  ``FakeClock.frozen()`` is a context manager that always restores the
original attributes, including on failure.
"""

from __future__ import annotations

import datetime as _datetime
from contextlib import contextmanager
from typing import Iterator


class FakeClock:
    """Advance a fixed calendar date and hand out deterministic Artifact identities.

    推进固定日历日期，并发放确定性的 Artifact 编号。
    """

    def __init__(self, start: _datetime.datetime) -> None:
        if not isinstance(start, _datetime.datetime):
            raise TypeError("FakeClock needs a datetime start")
        self._now = start
        self._ids = 0

    @property
    def now(self) -> _datetime.datetime:
        """Read the frozen current instant / 读取被冻结的当前时刻。"""
        return self._now

    def today(self) -> _datetime.date:
        """Read the frozen current calendar day / 读取被冻结的当前日历日。"""
        return self._now.date()

    def iso(self, timespec: str = "microseconds") -> str:
        """Format the frozen instant exactly like ``artifact._now`` / 按 ``artifact._now`` 格式输出。"""
        return self._now.isoformat(timespec=timespec)

    def advance(self, *, days: float = 0, hours: float = 0) -> _datetime.datetime:
        """Move the clock forward and return the new instant / 前进指定时长并返回新时刻。"""
        self._now = self._now + _datetime.timedelta(days=days, hours=hours)
        return self._now

    def next_artifact_id(self) -> str:
        """Return a stable Artifact identity that ignores wall-clock time / 返回忽略真实时间的稳定编号。"""
        self._ids += 1
        return f"n_{self._ids:08d}"

    def frozen(self) -> "Iterator[FakeClock]":
        """Freeze wall-clock symbols for one run and restore them afterwards.

        在一次运行中冻结真实时钟符号，结束后恢复。
        """
        return _frozen(self)


class _DateShim:
    """Expose ``date.today``/``date.fromisoformat`` over the frozen clock.

    在冻结时钟上提供 ``today`` 与 ``fromisoformat``。
    """

    @staticmethod
    def today() -> _datetime.date:
        return _CURRENT[0].today()

    @staticmethod
    def fromisoformat(value: str) -> _datetime.date:
        return _datetime.date.fromisoformat(value)

    def __getattr__(self, name: str):
        return getattr(_datetime.date, name)


class _DateTimeShim:
    """Expose ``datetime.now``/``datetime.fromisoformat`` over the frozen clock.

    在冻结时钟上提供 ``now`` 与 ``fromisoformat``。
    """

    @staticmethod
    def now(tz=None) -> _datetime.datetime:
        current = _CURRENT[0].now
        return current if tz is None else current.astimezone(tz)

    @staticmethod
    def fromisoformat(value: str) -> _datetime.datetime:
        return _datetime.datetime.fromisoformat(value)

    def __getattr__(self, name: str):
        return getattr(_datetime.datetime, name)


class _ModuleShim:
    """Stand in for the ``datetime`` module inside one patched module.

    在一个被替换的模块内代替 ``datetime`` 模块。
    """

    date = _DateShim
    datetime = _DateTimeShim
    timedelta = _datetime.timedelta
    timezone = _datetime.timezone


_CURRENT: list[FakeClock] = []


def _modules() -> list[tuple[object, str, object]]:
    """Import the patched modules lazily and capture their current symbols.

    延迟导入被替换模块并记录当前符号。
    """
    import core.domain.memory.artifact as artifact
    import maintain.expiry_policy as expiry
    import maintain.merge as merge
    import recall.assemble as assemble
    import recall.drift as drift
    import recall.score as score
    import recall.temporal as temporal
    import services.ingest_service as ingest
    import services.maintenance_service as maintenance

    return [
        (artifact, "_now", None),
        (artifact, "_new_id", None),
        (maintenance, "datetime", _ModuleShim),
        (ingest, "datetime", _ModuleShim),
        (expiry, "datetime", _ModuleShim),
        (merge, "datetime", _ModuleShim),
        (assemble, "date", _DateShim),
        (score, "date", _DateShim),
        (temporal, "date", _DateShim),
        (drift, "_today_ordinal", None),
    ]


@contextmanager
def _frozen(clock: FakeClock) -> Iterator[FakeClock]:
    """Install every clock-dependent symbol, then restore the originals / 安装全部时钟符号后恢复原值。"""
    _CURRENT.append(clock)
    originals: list[tuple[object, str, object]] = []
    try:
        for module, name, replacement in _modules():
            had = hasattr(module, name)
            originals.append((module, name, getattr(module, name, None), had))
            if name == "_now":
                setattr(module, name, lambda: clock.iso())
            elif name == "_new_id":
                setattr(module, name, clock.next_artifact_id)
            elif name == "_today_ordinal":
                setattr(module, name, lambda: float(clock.today().toordinal()))
            else:
                setattr(module, name, replacement)
        yield clock
    finally:
        for module, name, value, had in reversed(originals):
            if had:
                setattr(module, name, value)
            else:  # pragma: no cover - defensive for very old checkouts
                try:
                    delattr(module, name)
                except AttributeError:
                    pass
        _CURRENT.pop()


def parse_start(value: str) -> _datetime.datetime:
    """Parse the manifest start timestamp without consulting the wall clock / 解析清单起始时刻，不读取真实时钟。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("start timestamp is required")
    try:
        parsed = _datetime.datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"start timestamp is not ISO-8601: {value!r}") from exc
    if parsed.tzinfo is not None:
        raise ValueError("start timestamp must be naive local time")
    return parsed
