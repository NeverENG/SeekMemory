"""Compute existing impression matching and replacement content from supplied memories.

根据给定记忆计算既有印象匹配及替换内容，不执行读写。
"""

from __future__ import annotations

from dataclasses import replace

try:  # Plugin namespace / 插件命名空间。
    from ..core.artifact import Artifact, content_of, revise
    from .ports import ArtifactCache, ArtifactStore
    from ..app.text_rules import alphanumeric_bigrams as bigrams
except ImportError:  # Top-level package / 顶层包。
    from core.artifact import Artifact, content_of, revise
    from maintain.ports import ArtifactCache, ArtifactStore
    from app.text_rules import alphanumeric_bigrams as bigrams

LEVEL = "impression"
FAMILY = "memory"
REINFORCE_OVERLAP = 0.85   # Near-identical wording / 几乎同文时仅加证据。
REVISE_CONTAIN = 0.45      # Containment floor / 新旧印象包含度下限。
REVISE_DICE = 0.3          # Overall similarity floor / 同时要求整体相似度下限。
MIN_GRAMS = 4              # Minimum comparison size / 修订比较的最小大小。
WEIGHT_STEP = 0.1
WEIGHT_CAP = 3.0


def _text(art: Artifact) -> str:
    """Read memory text with existing malformed-row fallback / 按既有坏行回退读取记忆正文。"""
    try:
        text = content_of(art)
    except Exception:  # noqa: BLE001 - Isolate malformed impressions / 隔离格式错误的印象。
        text = ""
    return str(text or art.payload.get("text") or "").strip()


def rivals(pool: list[Artifact], art: Artifact) -> list[Artifact]:
    """Read supplied active impression rivals with matching subject and scope / 从给定有效印象中选择相同主体及范围的对手。"""
    out = []
    for old in pool:
        try:
            if old.header.id == art.header.id:
                continue
            if str(old.payload.get("level") or "") != LEVEL:
                continue
            if old.header.scope != art.header.scope:
                continue
            if str(old.header.subject_id or "") != str(art.header.subject_id or ""):
                continue
            out.append(old)
        except Exception:  # noqa: BLE001
            continue
    return out


def _compare(text: str, old_text: str) -> tuple[float, float]:
    """Compute existing Dice and minimum-size containment values / 计算既有 Dice 及较小集合包含度。"""
    a, b = bigrams(text), bigrams(old_text)
    if not a or not b:
        return 0.0, 0.0
    inter = len(a & b)
    dice = 2.0 * inter / (len(a) + len(b))
    contain = inter / max(1, min(len(a), len(b)))
    return dice, contain


def best_match(pool: list[Artifact], art: Artifact) -> tuple[Artifact | None, float, float]:
    """Select the supplied rival with the highest combined existing match value / 按既有组合匹配值选择给定最佳对手。"""
    text = _text(art)
    if not text:
        return None, 0.0, 0.0
    best, best_dice, best_contain = None, 0.0, 0.0
    for old in rivals(pool, art):
        try:
            dice, contain = _compare(text, _text(old))
        except Exception:  # noqa: BLE001
            continue
        if (dice + contain) > (best_dice + best_contain):
            best, best_dice, best_contain = old, dice, contain
    return best, best_dice, best_contain


def _merged_sources(old: Artifact, art: Artifact) -> tuple[str, ...]:
    """Deduplicate exact Source IDs from both impressions / 对两个印象的精确原始消息编号去重。"""
    return tuple(dict.fromkeys(
        tuple(old.header.lineage.sources) + tuple(art.header.lineage.sources)
    ))


def reinforced(art: Artifact, old: Artifact,
               weight: float, hits: int) -> Artifact:
    """Prepare the old impression with merged evidence and supplied strength / 以合并证据及给定强度准备旧印象新版本。"""
    sources = _merged_sources(old, art)
    lineage = replace(old.header.lineage, sources=sources)
    new = revise(old, strength=replace(old.header.strength, weight=weight, hits=hits),
                 lineage=lineage)
    return new


def reworded(art: Artifact, old: Artifact,
            weight: float, hits: int, score: float) -> Artifact:
    """Prepare revised impression wording with exact merged evidence / 以精确合并证据准备修订印象措辞。"""
    text = _text(art)
    payload = {**old.payload, **art.payload, "text": text}
    sources = _merged_sources(old, art)
    lineage = replace(
        old.header.lineage,
        sources=sources,
        derived_from=tuple(dict.fromkeys(
            old.header.lineage.derived_from + (art.header.id,))),
    )
    new = revise(
        old,
        payload,
        strength=replace(old.header.strength, weight=weight, hits=hits),
        lineage=lineage,
        scope=art.header.scope,
    )
    return new
