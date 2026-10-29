"""梦境周期：把人格与印象的进化收成每天一次。

白天只缓冲，不抽取；到了 ``dream_time`` 一次跑完当天积压：

    逐话题抽取 → 合并 / 修订印象 → 沉淀人格 → 落一条 dream 台账

台账主键是日期，所以同一天重跑幂等；中途失败会保留待处理行，下一次从断点续跑。
这里只做编排，具体抽取与整理由调用方注入，避免重复实现写入逻辑。
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from .console_ports import DreamRunStore


class FlushFn(Protocol):
    async def __call__(
        self,
        reason: str,
        *,
        max_calls: int = 0,
        max_tokens: int = 0,
        triage: bool = False,
    ) -> tuple[int, int]: ...

PendingFn = Callable[[], int]
MaintainFn = Callable[[], Awaitable[dict[str, Any]]]
Clock = Callable[[], datetime.datetime]
UsageFn = Callable[[], dict[str, Any]]
Log = Callable[[str], None]


def _usage_values(snapshot: dict[str, Any] | None) -> tuple[int, int, int, int]:
    data = snapshot if isinstance(snapshot, dict) else {}
    def number(key: str) -> int:
        try:
            return max(0, int(data.get(key, 0) or 0))
        except (TypeError, ValueError):
            return 0
    return number("calls"), number("in"), number("cached"), number("out")


def _usage_delta(
    baseline: tuple[int, int, int, int],
    current: tuple[int, int, int, int],
) -> dict[str, int]:
    return {
        "calls": max(0, current[0] - baseline[0]),
        "in": max(0, current[1] - baseline[1]),
        "cached": max(0, current[2] - baseline[2]),
        "out": max(0, current[3] - baseline[3]),
    }


@dataclass(frozen=True)
class DreamResult:
    """一次梦境的结论，供日志、报表与测试使用。"""

    date: str
    status: str
    reason: str = ""
    batches: int = 0
    written: int = 0
    errors: tuple[str, ...] = ()
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def ran(self) -> bool:
        return self.status in ("done", "failed")


class DreamCycle:
    """每天一次的进化周期；不持有模型与存储之外的状态。"""

    def __init__(self, dreams: DreamRunStore, conf: Callable[[str, Any], Any],
                 clock: Clock | None = None, log: Log | None = None) -> None:
        self.dreams = dreams
        self._c = conf
        self.clock = clock or datetime.datetime.now
        self.log = log or (lambda _msg: None)

    @property
    def enabled(self) -> bool:
        try:
            return bool(self._c("dream_enabled", True))
        except Exception:  # noqa: BLE001 - 配置坏了按开启处理，避免白天误抽取
            return True

    def _at(self) -> tuple[int, int]:
        """dream 时刻，格式 HH:MM；写错就退回 03:30。"""
        raw = str(self._c("dream_time", "03:30"))
        try:
            hour, minute = (int(x) for x in raw.split(":"))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return hour, minute
        except (TypeError, ValueError):
            pass
        return 3, 30

    def due(self, now: datetime.datetime | None = None) -> bool:
        """今天该不该做梦：到点了、还没做完。"""
        if not self.enabled:
            return False
        moment = now or self.clock()
        hour, minute = self._at()
        if (moment.hour, moment.minute) < (hour, minute):
            return False
        run = self.dreams.get(moment.date().isoformat())
        return run is None or run.get("status") != "done"

    async def run(self, flush_once: FlushFn, pending: PendingFn,
                  maintain: MaintainFn | None = None,
                  now: datetime.datetime | None = None,
                  usage: UsageFn | None = None) -> DreamResult:
        """跑一次梦境；幂等、可续跑、失败不丢待处理行。"""
        moment = now or self.clock()
        date = moment.date().isoformat()
        if not self.enabled:
            return DreamResult(date, "skipped", "disabled")
        if not self.due(moment):
            return DreamResult(date, "skipped", "not_due")
        if not self.dreams.begin(date, now=moment.isoformat(timespec="seconds")):
            return DreamResult(date, "skipped", "already_done")

        limit = max(1, int(self._c("dream_max_batches", 12)))
        max_calls = max(0, int(self._c("dream_max_calls", 12)))
        budget_tokens = max(0, int(self._c("dream_token_budget", 60000)))
        baseline = _usage_values(usage() if usage is not None else None)
        current_usage = baseline
        stopped = ""
        batches = written = 0
        errors: list[str] = []
        while batches < limit:
            if usage is not None:
                try:
                    current_usage = _usage_values(usage())
                except Exception:
                    current_usage = baseline
            used_calls = max(
                0, current_usage[0] - baseline[0]
            )
            used_tokens = max(
                0,
                current_usage[1] + current_usage[3]
                - baseline[1] - baseline[3],
            )
            if max_calls > 0 and used_calls >= max_calls:
                stopped = "call_budget"
                break
            if budget_tokens > 0 and used_tokens >= budget_tokens:
                stopped = "token_budget"
                break
            try:
                left = int(pending())
            except Exception as exc:  # noqa: BLE001 - 读不到就当作没有
                errors.append(f"pending: {type(exc).__name__}: {exc}")
                break
            if left <= 0:
                break
            remaining_calls = (
                max(0, max_calls - used_calls) if max_calls > 0 else 0
            )
            remaining_tokens = (
                max(0, budget_tokens - used_tokens) if budget_tokens > 0 else 0
            )
            try:
                got, count = await flush_once(
                    "梦境",
                    max_calls=remaining_calls,
                    max_tokens=remaining_tokens,
                    triage=True,
                )
            except Exception as exc:  # noqa: BLE001 - 保留待处理行，下次续跑
                errors.append(f"flush: {type(exc).__name__}: {exc}")
                break
            if not count:
                break
            batches += int(count)
            written += int(got)

        summary: dict[str, Any] = {}
        if maintain is not None and not errors:
            try:
                summary = dict(await maintain() or {})
            except Exception as exc:  # noqa: BLE001 - 整理失败不影响已抽取的记忆
                errors.append(f"maintain: {type(exc).__name__}: {exc}")

        if usage is not None:
            try:
                current_usage = _usage_values(usage())
            except Exception:
                current_usage = baseline
        usage_delta = _usage_delta(baseline, current_usage)
        used_calls = usage_delta["calls"]
        used_tokens = usage_delta["in"] + usage_delta["out"]
        summary["budget"] = {
            "calls": max_calls,
            "calls_used": used_calls,
            "tokens": budget_tokens,
            "used": used_tokens,
            "stopped": stopped,
        }
        summary["usage"] = usage_delta

        status = "done" if not errors else "failed"
        try:
            self.dreams.finish(
                date, status=status, batches=batches, written=written,
                errors=errors, summary=summary,
                now=moment.isoformat(timespec="seconds"),
            )
        except Exception as exc:  # noqa: BLE001
            self.log(f"梦境台账写入失败： {exc}")

        result = DreamResult(date, status, "ran", batches, written,
                             tuple(errors), summary)
        self.log(
            f"梦境 {date} {status}：{batches} 个话题，写入 {written} 条"
            + (f"，{len(errors)} 个错误" if errors else "")
        )
        return result

    def status(self, now: datetime.datetime | None = None) -> dict[str, Any]:
        """给面板/报表看的梦境状态。"""
        moment = now or self.clock()
        today = moment.date().isoformat()
        run = self.dreams.get(today)
        return {
            "enabled": self.enabled,
            "at": "%02d:%02d" % self._at(),
            "today": today,
            "today_run": run,
            "due": self.due(moment),
            "recent": self.dreams.recent(7),
        }
