"""纯内存 BM25 索引；只对调用方提供的可见候选池计分。"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass

try:
    from ..core.artifact import Artifact, content_of
    from .seed import tags_of
    from .tokenizer import tokenize
except ImportError:
    from core.artifact import Artifact, content_of
    from recall.seed import tags_of
    from recall.tokenizer import tokenize

K1 = 1.2
B = 0.75
DEFAULT_CALIBRATION_C = 8.0


@dataclass(frozen=True)
class _Document:
    text: Counter[str]
    tags: Counter[str]


class BM25Index:
    """可替换的 BM25 实现，支持全量重建和按 Artifact ID 更新。"""

    def __init__(self, calibration_c: float = DEFAULT_CALIBRATION_C) -> None:
        if not math.isfinite(calibration_c) or calibration_c <= 0:
            raise ValueError("calibration_c 必须大于 0")
        self.calibration_c = float(calibration_c)
        self._documents: dict[str, _Document] = {}
        self._postings: dict[str, dict[str, dict[str, int]]] = {"text": {}, "tags": {}}
        self._lengths: dict[str, dict[str, int]] = {"text": {}, "tags": {}}

    def rebuild(self, artifacts: list[Artifact]) -> None:
        """从活跃缓存快照重建索引。"""
        self._documents.clear()
        for field in self._postings:
            self._postings[field].clear()
            self._lengths[field].clear()
        for art in artifacts:
            self.put(art)

    def put(self, art: Artifact) -> None:
        """新增或替换一条记忆的索引文档。"""
        self.remove(art.header.id)
        if art.header.state != "active":
            return
        try:
            text = content_of(art)
            tags = tags_of(art)
        except (TypeError, ValueError):
            return
        document = _Document(
            Counter(tokenize(text)),
            Counter(token for tag in tags for token in tokenize(tag)),
        )
        self._documents[art.header.id] = document
        for field in self._postings:
            tokens = getattr(document, field)
            self._lengths[field][art.header.id] = sum(tokens.values())
            for term, frequency in tokens.items():
                self._postings[field].setdefault(term, {})[art.header.id] = frequency

    def remove(self, artifact_id: str) -> None:
        """移除一条已索引的记忆。"""
        document = self._documents.pop(artifact_id, None)
        if document is None:
            return
        for field in self._postings:
            self._lengths[field].pop(artifact_id, None)
            for term in getattr(document, field):
                postings = self._postings[field][term]
                postings.pop(artifact_id, None)
                if not postings:
                    del self._postings[field][term]

    def search(self, query: str, pool: list[Artifact]) -> dict[str, float]:
        """返回本次候选池中归一化后的 BM25 分数，范围为 0 到 1。"""
        terms = tuple(dict.fromkeys(tokenize(query)))
        if not terms or not pool:
            return {}

        allowed_ids = {art.header.id for art in pool if art.header.id in self._documents}
        if not allowed_ids:
            return {}

        text_scores = self._field_scores(terms, allowed_ids, "text")
        tag_scores = self._field_scores(terms, allowed_ids, "tags")
        scores: dict[str, float] = {}
        for artifact_id in sorted(text_scores.keys() | tag_scores.keys()):
            text_score = text_scores.get(artifact_id, 0.0)
            tag_score = tag_scores.get(artifact_id, 0.0)
            value = 0.75 * self._normalize(text_score)
            value += 0.25 * self._normalize(tag_score)
            if value > 0.0:
                scores[artifact_id] = value
        return scores

    def _field_scores(self, terms: tuple[str, ...], allowed_ids: set[str],
                      field: str) -> dict[str, float]:
        count = len(allowed_ids)
        if not count:
            return {}
        lengths = self._lengths[field]
        average_length = sum(lengths[artifact_id] for artifact_id in allowed_ids) / count
        if average_length <= 0:
            return {}

        scores: dict[str, float] = {}
        for term in terms:
            postings = self._postings[field].get(term, {})
            matching_ids = allowed_ids.intersection(postings)
            document_frequency = len(matching_ids)
            if not document_frequency:
                continue
            inverse_frequency = math.log1p(
                (count - document_frequency + 0.5) / (document_frequency + 0.5)
            )
            for artifact_id in sorted(matching_ids):
                frequency = postings[artifact_id]
                length_ratio = lengths[artifact_id] / average_length
                denominator = frequency + K1 * (1.0 - B + B * length_ratio)
                scores[artifact_id] = scores.get(artifact_id, 0.0) + (
                    inverse_frequency * frequency * (K1 + 1.0) / denominator
                )
        return scores

    def _normalize(self, score: float) -> float:
        return score / (score + self.calibration_c) if score > 0.0 else 0.0
