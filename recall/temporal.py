"""Apply existing date validity and relative-window rules without time conversion or writes.

应用既有日期有效性及相对窗口规则，不转换时间或执行写入。
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Iterable

try:
    from ..core.artifact import Artifact
except ImportError:
    from core.artifact import Artifact


def as_date(value: str | None) -> date | None:
    """Parse the existing first-ten-character ISO calendar date / 解析既有前十字符 ISO 日历日期。"""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def valid_at(art: Artifact, today: date | None = None) -> bool:
    """Check existing inclusive validity and expiry dates / 检查既有包含边界的有效及过期日期。"""
    moment = today or date.today()
    span = art.header.time
    lower = as_date(span.valid_from)
    upper = as_date(span.valid_to)
    expiry = as_date(span.expires)
    if lower is not None and moment < lower:
        return False
    if upper is not None and moment > upper:
        return False
    if expiry is not None and moment > expiry:
        return False
    return True


def filter_valid(arts: Iterable[Artifact], today: date | None = None) -> list[Artifact]:
    """Keep memories valid on the supplied or existing current day / 保留给定日或既有当前日有效的记忆。"""
    return [art for art in arts if valid_at(art, today)]


def _next_month(day: date) -> date:
    """Read the first calendar day of the following month / 读取下个月的首个日历日。"""
    return date(day.year + (1 if day.month == 12 else 0),
                1 if day.month == 12 else day.month + 1, 1)


def query_window(text: str, today: date | None = None) -> tuple[date, date] | None:
    """Resolve existing Chinese relative-date expressions into inclusive ranges / 将既有中文相对日期表达转换为包含边界的范围。"""
    raw = str(text or "")
    moment = today or date.today()
    if "\u4eca\u5929" in raw:
        return moment, moment
    if "\u660e\u5929" in raw:
        one = moment + timedelta(days=1)
        return one, one
    if "\u6628\u5929" in raw:
        one = moment - timedelta(days=1)
        return one, one
    if "\u4e0b\u5468" in raw:
        start = moment - timedelta(days=moment.weekday()) + timedelta(days=7)
        return start, start + timedelta(days=6)
    if "\u8fd9\u5468" in raw or "\u672c\u5468" in raw:
        start = moment - timedelta(days=moment.weekday())
        return start, start + timedelta(days=6)
    if "\u4e0b\u4e2a\u6708" in raw:
        start = _next_month(moment)
        end = date(start.year, start.month,
                   calendar.monthrange(start.year, start.month)[1])
        return start, end
    if "\u8fd9\u4e2a\u6708" in raw or "\u672c\u6708" in raw:
        start = date(moment.year, moment.month, 1)
        end = date(moment.year, moment.month,
                   calendar.monthrange(moment.year, moment.month)[1])
        return start, end
    if "\u660e\u5e74" in raw:
        start = date(moment.year + 1, 1, 1)
        return start, date(moment.year + 1, 12, 31)
    if "\u4eca\u5e74" in raw:
        return date(moment.year, 1, 1), date(moment.year, 12, 31)
    return None


def event_date(art: Artifact) -> date | None:
    """Read creation date with the existing validity-start fallback / 读取创建日期，并保留既有有效起始日期回退。"""
    span = art.header.time
    return as_date(span.created) or as_date(span.valid_from)


def in_window(art: Artifact, window: tuple[date, date] | None) -> bool:
    """Apply inclusive event-date bounds; absent bounds allow all / 应用包含边界的事件日期范围，无范围时全部允许。"""
    if window is None:
        return True
    day = event_date(art)
    if day is None:
        return False
    return window[0] <= day <= window[1]
