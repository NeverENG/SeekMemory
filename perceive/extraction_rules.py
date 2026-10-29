"""Compute existing extraction attributes and gates without storage writes.

计算既有抽取属性和条件，不写存储；保留时间、主体和强度计算行为。
"""
from __future__ import annotations

import datetime
import math
import re
from typing import Any

try:
    from ..app.contracts import DialogueTurn
    from ..core.artifact import Strength
except ImportError:
    from app.contracts import DialogueTurn
    from core.artifact import Strength
from .behavior import DEFAULT_BEHAVIOR_CONFIDENCE, is_behavior

# Legacy urgency signals; the external scheduling gate decides when to extract.
# 旧紧急信号，由外部调度条件决定何时抽取。
_PLAN = re.compile(
    r"(下周|明天|后天|下个月|周末|计划|打算|准备|约了|要去|出差|搬家|"
    r"面试|入职|离职|辞职|生日|纪念日|考试|体检)"
)
_FACT = re.compile(
    r"(我叫|名字|住在|老家|公司|工作|职业|女朋友|男朋友|老婆|老公|对象|"
    r"爸|妈|猫|狗|住院|手术|升职|加薪|毕业)"
)
_STRONG = re.compile(
    r"(崩溃|吵架|分手|哭了|想死|撑不住|很难受|被骂|裁员|辞退|生病|发烧)"
)
_NOT_WORTH = re.compile(
    r"^(早|晚安|在吗|在不在|哈哈|嗯|哦|好|好的|收到)[。！？!?~～]*$"
)


def _parse_time(value: Any) -> datetime.datetime | None:
    """Parse with the existing ISO/fallback rules, without timezone conversion / 沿用既有 ISO 及回退解析规则，不转换时区。"""
    try:
        return datetime.datetime.fromisoformat(str(value or "").strip())
    except (TypeError, ValueError):
        try:
            return datetime.datetime.fromisoformat(
                str(value or "").strip() + "T00:00:00"
            )
        except (TypeError, ValueError):
            return None


def _date_or_none(value: Any) -> str | None:
    """Read the parsed calendar date or None / 读取解析后的日历日期，无效时返回空。"""
    parsed = _parse_time(value)
    return parsed.date().isoformat() if parsed is not None else None


def _event_at(item: dict, turns: list[DialogueTurn]) -> str:
    """Use the existing explicit event, validity or earliest-evidence time fallback / 沿用明确事件、有效期或最早证据时间的既有回退顺序。"""
    parsed = _parse_time(item.get("event_at"))
    if parsed is not None:
        return parsed.isoformat(timespec="seconds")
    wanted = item.get("event_date") or item.get("valid_from")
    parsed = _parse_time(wanted)
    if parsed is not None:
        return parsed.isoformat(timespec="seconds")
    stamps = [_parse_time(turn.at) for turn in turns]
    valid = [stamp for stamp in stamps if stamp is not None]
    if valid:
        return min(valid).isoformat(timespec="seconds")
    return datetime.datetime.now().isoformat(timespec="seconds")


def _subject_id(item: dict, owner: str, default: str, owner_id: str = "") -> str:
    """Resolve the interpreted subject without confusing it with the speaker / 确定被解释对象，不将其与说话人混用。"""
    kind = str(item.get("subject_kind") or "").strip()
    raw = str(item.get("subject_id") or "").strip()
    if raw and raw not in ("owner", "speaker", "self", "world", "relation"):
        return raw
    if not owner_id and owner:
        owner_id = str(owner).split(":")[-1]
    if kind == "owner":
        return owner_id or default
    if kind == "speaker":
        return default
    if kind in ("world", "relation", "self"):
        return kind
    name = str(item.get("subject_name") or "").strip()
    return "third:" + name if name else default


def _num(value: Any, default: float, low: float, high: float) -> float:
    """Clamp finite model numbers; invalid values use the existing default / 限定模型数值为有限范围，无效值使用既有默认值。"""
    if isinstance(value, bool):
        return default
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(low, min(high, number))


def strength_of(item: dict) -> dict:
    """Prepare existing emotional/confidence/hit values without reinforcement / 准备既有情绪、置信度及命中值，不执行强化。"""
    base = Strength()
    out = {
        "arousal": _num(item.get("arousal"), base.arousal, 0.0, 1.0),
        "valence": _num(item.get("valence"), base.valence, -1.0, 1.0),
        "funny": _num(item.get("funny"), base.funny, 0.0, 1.0),
    }
    if "confidence" in item or is_behavior(item):
        # Preserve conservative behavior confidence and legacy ordinary-fact defaults.
        # 保留保守行为置信度及旧普通事实默认值。
        default = DEFAULT_BEHAVIOR_CONFIDENCE if is_behavior(item) else base.confidence
        out["confidence"] = _num(item.get("confidence"), default, 0.0, 1.0)
    hits = item.get("hits")
    if hits is not None:
        try:
            out["hits"] = max(0, int(hits))
        except (TypeError, ValueError):
            pass
    return out


def worth_now(items: list[DialogueTurn]) -> bool:
    """Read the existing user-memory urgency signal; scheduling gates remain external / 读取既有用户记忆紧急信号，调度条件仍由外部管理。"""
    for turn in items[-30:]:
        if turn.role != "user":
            continue
        line = str(turn.text or "").strip()
        if not line or _NOT_WORTH.match(line):
            continue
        if _PLAN.search(line) or _FACT.search(line) or _STRONG.search(line):
            return True
    return False




def _boundary(scope: str, subject_id: str) -> str:
    """Build the existing subject/scope deduplication key / 构造既有主体及范围去重键。"""
    return f"{scope}\x1f{subject_id}"
