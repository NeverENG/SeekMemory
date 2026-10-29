"""Find lexical graph seeds with bounded derived indices invalidated by pool/object identity.

以有界派生索引查找字面图种子，按候选池及对象身份失效。
"""

from __future__ import annotations

import re
from collections import OrderedDict, defaultdict

try:  # Plugin namespace / 插件命名空间。
    from ..core.artifact import Artifact, content_of
except ImportError:  # Top-level package / 顶层包。
    from core.artifact import Artifact, content_of

MEME_WORDS: tuple[str, ...] = ("咕咕嘎嘎", "原神", "鸣潮", "抽象", "哈基米")
MEME_BONUS = 0.75
MEME_BONUS_CAP = 1.5

INDEX_CACHE_LIMIT = 8
ART_CACHE_LIMIT = 20_000

# Retain pool references so object IDs remain valid / 保留池强引用以保证对象编号有效。
_INDEX_CACHE: OrderedDict[tuple, tuple[list, dict, dict, list]] = OrderedDict()
_ART_CACHE: OrderedDict[int, tuple[Artifact, frozenset[str], tuple[str, ...]]] = OrderedDict()


try:
    from ..app.text_rules import alphanumeric_bigrams as bigrams, _PUNCT
except ImportError:
    from app.text_rules import alphanumeric_bigrams as bigrams, _PUNCT


def overlap(text: str, content: str) -> float:
    """Compute existing character-pair Dice overlap / 计算既有字符二元组 Dice 重合度。"""
    a, b = bigrams(text), bigrams(content)
    if not a or not b:
        return 0.0
    return 2.0 * len(a & b) / (len(a) + len(b))


def dice(grams: frozenset[str] | set[str], total: int,
         other: frozenset[str] | set[str]) -> float:
    """Compute Dice from precomputed character-pair sets / 从预计算字符二元组集合计算 Dice。"""
    if not grams or not other:
        return 0.0
    return 2.0 * len(grams & other) / (total + len(other))


def tags_of(art: Artifact) -> list[str]:
    """Read supported normalized tag layouts / 读取受支持的规范标签布局。"""
    raw = art.payload.get("tags") or art.payload.get("tag") or []
    if isinstance(raw, str):
        raw = re.split(r"[\s,，#]+", raw)
    return [str(tag).strip().lower() for tag in raw if str(tag).strip()]


def _content(art: Artifact) -> str:
    """Read content with the existing malformed-memory fallback / 按既有坏记忆回退读取内容。"""
    try:
        return content_of(art)
    except Exception:
        return str(art.payload.get("text") or "")


def _art_info(art: Artifact) -> tuple[frozenset[str], tuple[str, ...]]:
    """Cache grams and tags by retained Artifact object identity / 按保留的记忆对象身份缓存二元组及标签。"""
    key = id(art)
    cached = _ART_CACHE.get(key)
    if cached is not None:
        _ART_CACHE.move_to_end(key)
        return cached[1], cached[2]
    grams = frozenset(bigrams(_content(art)))
    try:
        tags = tuple(tags_of(art))
    except Exception:
        tags = ()
    _ART_CACHE[key] = (art, grams, tags)
    if len(_ART_CACHE) > ART_CACHE_LIMIT:
        _ART_CACHE.popitem(last=False)
    return grams, tags


def signals_of(art: Artifact) -> tuple[frozenset[str], tuple[str, ...]]:
    """Read shared cached lexical signals for scoring / 读取供评分共用的缓存字面信号。"""
    return _art_info(art)


def _pool_fingerprint(pool: list[Artifact]) -> tuple:
    """Invalidate on pool length, list identity or element identity changes / 在池长度、列表身份或元素身份变化时失效。"""
    return (len(pool), id(pool), tuple(id(art) for art in pool))


def _build_index(pool: list[Artifact]) -> tuple[list, dict, dict, list]:
    """Build bounded-pool postings and keep strong references for identity validity / 构造候选池倒排项，并保留强引用以确保身份有效。"""
    postings: defaultdict[str, list[int]] = defaultdict(list)
    tag_postings: defaultdict[str, list[int]] = defaultdict(list)
    items: list[tuple[str, frozenset[str], tuple[str, ...]]] = []
    for index, art in enumerate(pool):
        grams, tags = _art_info(art)
        items.append((art.header.id, grams, tags))
        for gram in grams:
            postings[gram].append(index)
        for tag in tags:
            tag_postings[tag].append(index)
    return (pool, postings, tag_postings, items)


def _index_for(pool: list[Artifact]) -> tuple[list, dict, dict, list]:
    """Reuse the pool fingerprint or rebuild with bounded eviction / 复用池指纹索引，或重建并限量淘汰。"""
    fingerprint = _pool_fingerprint(pool)
    cached = _INDEX_CACHE.get(fingerprint)
    if cached is not None:
        _INDEX_CACHE.move_to_end(fingerprint)
        return cached
    index = _build_index(pool)
    _INDEX_CACHE[fingerprint] = index
    while len(_INDEX_CACHE) > INDEX_CACHE_LIMIT:
        _INDEX_CACHE.popitem(last=False)
    return index


def seeds(text: str, pool: list[Artifact], limit: int = 5) -> list[str]:
    """Read top matching graph seed IDs using existing Dice/tag bonuses / 按既有 Dice 及标签加分读取最高匹配图种子编号。"""
    if not text or limit <= 0 or not pool:
        return []
    wanted = [word for word in MEME_WORDS if word in text]
    _, postings, tag_postings, items = _index_for(pool)
    grams = frozenset(bigrams(text))
    total = len(grams)
    candidates: set[int] = set()
    for gram in grams:
        hit = postings.get(gram)
        if hit:
            candidates.update(hit)
    for word in wanted:
        for tag, hit in tag_postings.items():
            if word in tag:
                candidates.update(hit)

    ranked: list[tuple[float, str]] = []
    for index in candidates:
        node_id, other, tags = items[index]
        value = dice(grams, total, other) if total and other else 0.0
        if wanted:
            hits = sum(1 for word in wanted if any(word in tag for tag in tags))
            value += min(MEME_BONUS_CAP, hits * MEME_BONUS)
        if value > 0:
            ranked.append((value, node_id))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [node_id for _, node_id in ranked[:limit]]
