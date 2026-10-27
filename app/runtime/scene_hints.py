"""场景提示：告诉模型"现在几点、对面是谁、该怎么拿捏分寸"。

只产出提示文本，不碰人格正文（人格已由 persona 链路注入）。
纯函数，便于单测；时间窗与亲疏都来自 Signals，避免重复实现。
"""

from __future__ import annotations

from .contracts import AttentionLevel, RuntimeInput
from .signals import Signals

DAY_START = 8
EVENING_START = 18
LATE_START = 0
LATE_END = 6

WINDOW_LINES = {
    "day": "现在是白天，对方可能在忙：话少一点，一两句就够，带一句关心。",
    "evening": "现在是晚上，可以多聊两句，语气放松一点。",
    "late": "现在是深夜：轻声一点，别拖着不睡，可以催他去休息。",
}


def time_window(hour: int) -> str:
    """把小时映射到 day / evening / late 三档。"""
    if LATE_START <= hour < LATE_END:
        return "late"
    if hour < DAY_START:
        return "late"
    if hour < EVENING_START:
        return "day"
    return "evening"


def role_line(event: RuntimeInput) -> str:
    """按说话人身份给一句分寸提示。"""
    if event.private:
        return "现在是私聊，对面就是你自己人，可以亲近、可以闹。"
    if event.is_owner:
        return "群里说话的是主人：可以亲近，但别抢他和其他人的话。"
    if event.role == "admin":
        return "群里说话的是管理员：客气、得体，别越界。"
    return "群里说话的是其他人：客气有距离，不认亲，别主动热络。"


def closeness_line(signals: Signals) -> str:
    """按关系分给一句亲疏提示。"""
    if signals.relationship >= 0.6:
        return "你对这个人印象很深，可以熟络一点。"
    if signals.relationship >= 0.3:
        return "你对这个人有印象，正常聊就好。"
    return "你对这个人几乎没有印象，别装熟。"


def compose(
    event: RuntimeInput,
    signals: Signals,
    now_hour: int,
    attention: AttentionLevel = AttentionLevel.AMBIENT,
) -> str:
    """组合成一段可注入的场景提示；没有内容时返回空串。"""
    parts = [WINDOW_LINES.get(time_window(now_hour), "")]
    parts.append(role_line(event))
    if not event.private and attention is not AttentionLevel.PRIVATE:
        parts.append(closeness_line(signals))
    return "".join(part for part in parts if part)
