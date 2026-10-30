"""Define neutral retrieval candidate data without retrieval execution or I/O.

定义中立检索候选数据，不执行检索或读写。
"""
from __future__ import annotations

from dataclasses import dataclass

from .artifact import Artifact


@dataclass(frozen=True)
class RetrievalCandidate:
    """Pair an Artifact with graph activation and lexical evidence.

    将 Artifact 与图激活及字面证据配对。
    """
    artifact: Artifact
    activation: float = 0.0
    lexical: float = 0.0
