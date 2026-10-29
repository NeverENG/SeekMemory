"""Pure daily-cycle time and budget rules; no clock, model or storage access.

每日整理的纯时间与预算规则；不读取时钟，不调用模型或存储。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NamedTuple


class UsageSnapshot(NamedTuple):
    """Normalized cumulative usage / 规整后的累计用量。"""

    calls: int = 0
    incoming: int = 0
    cached: int = 0
    outgoing: int = 0


def parse_time(raw: str) -> tuple[int, int]:
    """Parse HH:MM, falling back to 03:30 / 解析 HH:MM，非法时使用 03:30。"""
    try:
        hour, minute = (int(x) for x in raw.split(":"))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute
    except (TypeError, ValueError):
        pass
    return 3, 30


def usage_values(snapshot: dict[str, Any] | None) -> UsageSnapshot:
    """Clamp invalid/negative counters to zero / 将非法或负用量规整为零。"""
    data = snapshot if isinstance(snapshot, dict) else {}
    def number(key: str) -> int:
        """Normalize one counter without reading external state / 规整一个计数器，不读取外部状态。"""
        try:
            return max(0, int(data.get(key, 0) or 0))
        except (TypeError, ValueError):
            return 0
    return UsageSnapshot(number("calls"), number("in"), number("cached"), number("out"))


def usage_delta(baseline: UsageSnapshot, current: UsageSnapshot) -> dict[str, int]:
    """Return nonnegative per-counter usage since baseline / 返回各计数器相对基线的非负用量。"""
    return {
        "calls": max(0, current.calls - baseline.calls),
        "in": max(0, current.incoming - baseline.incoming),
        "cached": max(0, current.cached - baseline.cached),
        "out": max(0, current.outgoing - baseline.outgoing),
    }


@dataclass(frozen=True)
class DreamBudget:
    """One run's limits; zero calls/tokens means unlimited / 一次整理的限额，调用数或用量为零表示不限。"""

    batches: int
    calls: int
    tokens: int

    def stopped(self, used_calls: int, used_tokens: int) -> str:
        """Return the first exhausted limit, or empty / 返回首个耗尽限额，无则返回空。"""
        if self.calls > 0 and used_calls >= self.calls:
            return "call_budget"
        if self.tokens > 0 and used_tokens >= self.tokens:
            return "token_budget"
        return ""

    def remaining_calls(self, used: int) -> int:
        """Return remaining calls, preserving zero as unlimited / 返回剩余调用数，零仍表示不限。"""
        return max(0, self.calls - used) if self.calls > 0 else 0

    def remaining_tokens(self, used: int) -> int:
        """Return remaining tokens, preserving zero as unlimited / 返回剩余用量，零仍表示不限。"""
        return max(0, self.tokens - used) if self.tokens > 0 else 0
