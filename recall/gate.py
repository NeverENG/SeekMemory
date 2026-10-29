"""Choose pinned memory and existing evidence/clock gates; no persistence.

选择常驻记忆及应用既有证据和时间查询条件，不持久化。
"""

from __future__ import annotations

# Evidence must meet absolute and relative floors / 证据必须同时满足绝对及相对下限。
# Keep the existing calibrated evidence scale / 保留既有校准证据量级。
MIN_EV_ABS = 0.5
MIN_EV_REL = 0.3

# Pin one active persona and the top weighted impressions / 常驻一个有效人格及最高权重印象。
OWNER_SAID_BY = ("owner", "inferred", "")
MAX_PINNED_IMPRESSION = 2

# A pure clock query needs a clock term and no remaining meaningful words.
# 纯时间问题需要时间词且去除填充词后没有剩余实义词。
CLOCK_MARKERS = ("几号", "几月", "星期", "礼拜", "周几", "几点", "日期",
                 "什么日子", "多少号", "几点了", "几号了")
CLOCK_FILLERS = tuple(sorted((
    "今天", "明天", "昨天", "现在", "当前", "目前", "请问", "问一下",
    "几号", "几月", "几日", "星期", "礼拜", "周几", "几点", "日期",
    "什么日子", "多少号", "多少", "时间", "是", "的", "了", "吗", "呢",
    "啊", "呀", "吧", "么", "那", "这", "号", "日", "几", "点",
), key=len, reverse=True))


def evidence_floor(top_evidence: float,
                   min_ev_abs: float | None = None,
                   min_ev_rel: float | None = None) -> float:
    """Use the greater of absolute and best-evidence-relative thresholds / 取绝对阈值与最高证据相对阈值中的较大值。"""
    abs_floor = MIN_EV_ABS if min_ev_abs is None else float(min_ev_abs)
    rel = MIN_EV_REL if min_ev_rel is None else float(min_ev_rel)
    return max(abs_floor, float(top_evidence) * rel)


def _weight(art) -> float:
    """Read and bound the existing weight with a zero invalid-value fallback / 读取并限定既有权重，无效值回退为零。"""
    try:
        return float(art.header.strength.weight)
    except Exception:  # noqa: BLE001
        return 0.0


def pinned(cache, subject: str = "") -> list:
    """Read one active persona and bounded speaker impressions / 读取一个有效人格及有数量上限的说话人印象。"""
    try:
        active = list(cache.active())
    except Exception:  # noqa: BLE001 - Missing pins do not block chat / 常驻项缺失不阻塞聊天。
        return []
    who = str(subject or "")
    allowed = set(OWNER_SAID_BY) if who in ("", "owner") else {who}
    if who:
        allowed.add(who)
    personas, impressions = [], []
    for art in active:
        try:
            if art.header.family == "persona":
                personas.append(art)
            elif (str(art.payload.get("level") or "") == "impression"
                  and str(art.header.said_by or "") in allowed):
                impressions.append(art)
        except Exception:  # noqa: BLE001 - Skip a malformed row / 跳过格式错误的行。
            continue
    impressions.sort(key=lambda a: (-_weight(a), a.header.id))
    if personas:
        # Select the newest legacy persona deterministically; the active chain is unique.
        # 确定性选择最新旧人格，有效版本链保持唯一。
        personas.sort(key=lambda a: (
            int(getattr(a.header, "revision", 0) or 0),
            str(getattr(a.header.time, "updated", "") or ""),
            a.header.id,
        ))
        personas = personas[-1:]
    return personas + impressions[:MAX_PINNED_IMPRESSION]


def is_clock_query(text: str) -> bool:
    """Recognize pure short time questions without treating errors as matches / 识别纯短时间问题，不把错误当作匹配。"""
    try:
        raw = "".join(ch for ch in str(text or "") if ch.isalnum())
        if not raw or not any(marker in raw for marker in CLOCK_MARKERS):
            return False
        rest = raw
        for word in CLOCK_FILLERS:
            if word in rest:
                rest = rest.replace(word, "")
        # Allow one filler character; meaningful remainder implies a broader query.
        # 允许一个语气残字，剩余实义词表示更广泛的问题。
        return len(rest) <= 1
    except Exception:  # noqa: BLE001 - Failed detection does not block recall / 检测失败不阻塞召回。
        return False
