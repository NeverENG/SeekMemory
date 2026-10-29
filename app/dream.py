"""Coordinate daily extraction, maintenance and journal writes through injected ports.

通过注入能力编排每日抽取、维护及台账写入；不创建模型、连接或后台任务。
Completed dates are skipped; unfinished input can resume on a later run.
已完成日期跳过，未完成输入可在后续运行续跑。
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from .console_ports import DreamRunStore
from .contracts import ExtractionFailure
from .dream_policy import DreamBudget, parse_time, usage_values as _usage_values, usage_delta as _usage_delta


class FlushFn(Protocol):
    """Extract one bounded batch / 执行一次限量抽取。"""

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


@dataclass(frozen=True)
class DreamResult:
    """Daily outcome and completed counts / 每日整理结果及已完成数量。"""

    date: str
    status: str
    reason: str = ""
    batches: int = 0
    written: int = 0
    errors: tuple[str, ...] = ()
    summary: dict[str, Any] = field(default_factory=dict)

    @property
    def ran(self) -> bool:
        """Whether the cycle ran, including a failed run / 是否实际运行过，包含失败的整理。"""
        return self.status in ("done", "failed")


class DreamCycle:
    """Own daily orchestration, not extraction rules / 管理每日编排，不实现抽取规则。"""

    def __init__(self, dreams: DreamRunStore, conf: Callable[[str, Any], Any],
                 clock: Clock | None = None, log: Log | None = None) -> None:
        self.dreams = dreams
        self._c = conf
        self.clock = clock or datetime.datetime.now
        self.log = log or (lambda _msg: None)

    @property
    def enabled(self) -> bool:
        """Read the switch, defaulting to enabled on config failure / 读取开关，配置失败时默认开启。"""
        try:
            return bool(self._c("dream_enabled", True))
        except Exception:  # noqa: BLE001 - preserve night gating / 保留夜间门控
            return True

    def _at(self) -> tuple[int, int]:
        """Read the configured local time / 读取已配置的本地执行时间。"""
        return parse_time(str(self._c("dream_time", "03:30")))

    def due(self, now: datetime.datetime | None = None) -> bool:
        """Check enabled, local time and unfinished date / 检查开关、当地时间及当天是否未完成。"""
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
        """Run bounded extraction then maintenance; preserve completed writes.

        限量抽取后执行维护，保留已经完成的写入。
        """
        moment = now or self.clock()
        date = moment.date().isoformat()
        if not self.enabled:
            return DreamResult(date, "skipped", "disabled")
        if not self.due(moment):
            return DreamResult(date, "skipped", "not_due")
        if not self.dreams.begin(date, now=moment.isoformat(timespec="seconds")):
            return DreamResult(date, "skipped", "already_done")

        budget = DreamBudget(
            max(1, int(self._c("dream_max_batches", 12))),
            max(0, int(self._c("dream_max_calls", 12))),
            max(0, int(self._c("dream_token_budget", 60000))),
        )
        baseline = _usage_values(usage() if usage is not None else None)
        current_usage = baseline
        stopped = ""
        batches = written = 0
        errors: list[str] = []
        while batches < budget.batches:
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
            stopped = budget.stopped(used_calls, used_tokens)
            if stopped:
                break
            try:
                left = int(pending())
            except Exception as exc:  # noqa: BLE001 - stop without consuming input / 停止且不消费输入
                errors.append(f"pending: {type(exc).__name__}")
                break
            if left <= 0:
                break
            remaining_calls = budget.remaining_calls(used_calls)
            remaining_tokens = budget.remaining_tokens(used_tokens)
            try:
                got, count = await flush_once(
                    "梦境",
                    max_calls=remaining_calls,
                    max_tokens=remaining_tokens,
                    triage=True,
                )
            except Exception as exc:  # noqa: BLE001 - retain input for resume / 保留输入以便续跑
                if isinstance(exc, ExtractionFailure):
                    written += exc.written
                    batches += exc.topics
                errors.append(f"flush: {type(exc).__name__}")
                break
            if not count:
                break
            batches += int(count)
            written += int(got)

        summary: dict[str, Any] = {}
        if maintain is not None and not errors:
            try:
                summary = dict(await maintain() or {})
            except Exception as exc:  # noqa: BLE001 - preserve extracted memory / 保留已抽取记忆
                errors.append(f"maintain: {type(exc).__name__}")

        if usage is not None:
            try:
                current_usage = _usage_values(usage())
            except Exception:
                current_usage = baseline
        usage_delta = _usage_delta(baseline, current_usage)
        used_calls = usage_delta["calls"]
        used_tokens = usage_delta["in"] + usage_delta["out"]
        summary["budget"] = {
            "calls": budget.calls,
            "calls_used": used_calls,
            "tokens": budget.tokens,
            "used": used_tokens,
            "stopped": stopped,
        }
        summary["usage"] = usage_delta

        status = "done" if not errors else "failed"
        reason = "ran"
        try:
            self.dreams.finish(
                date, status=status, batches=batches, written=written,
                errors=errors, summary=summary,
                now=moment.isoformat(timespec="seconds"),
            )
        except Exception as exc:  # noqa: BLE001 - writes already completed / 已有写入不回滚
            status = "failed"
            reason = "journal_finish_failed"
            errors.append(f"journal_finish: {type(exc).__name__}")

        result = DreamResult(date, status, reason, batches, written,
                             tuple(errors), summary)
        self._log(
            f"梦境 {date} {status}：{batches} 个话题，写入 {written} 条"
            + (f"，{len(errors)} 个错误" if errors else "")
        )
        return result

    def _log(self, message: str) -> None:
        """Keep diagnostic failures outside business outcomes / 诊断失败不改变业务结果。"""
        try:
            self.log(message)
        except Exception:
            pass

    def status(self, now: datetime.datetime | None = None) -> dict[str, Any]:
        """Read current and recent journal status / 读取当前及近期台账状态。"""
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
