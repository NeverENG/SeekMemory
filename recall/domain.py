"""Explicit provided recall capabilities; no query or write implementation here.

明确召回模块对外能力，此处不实现查询或写入；旧实现路径继续可用。
"""
from .pipeline import build_block, query_block
from .context_recording import ContextRecorder, record_context
from .retriever import GraphRetriever, HybridRetriever
from .bm25 import BM25Index
from .assemble import build, build_with_meta
from .source_query import SourceHit, query_recent
from .scope import owner_of, visible
from .designated import deliverable, mark_given
from .seed import seeds, bigrams, overlap, dice, tags_of
from .score import score, select
from .temporal import filter_valid, query_window, in_window

__all__ = [
    "build_block", "query_block", "ContextRecorder", "record_context", "GraphRetriever", "HybridRetriever", "BM25Index",
    "build", "build_with_meta", "SourceHit", "query_recent", "owner_of", "visible",
    "deliverable", "mark_given", "seeds", "bigrams", "overlap", "dice", "tags_of",
    "score", "select", "filter_valid", "query_window", "in_window",
]
