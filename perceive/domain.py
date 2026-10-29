"""Explicit extraction capabilities; re-exports only.

明确抽取模块对外能力，仅导出；旧实现路径保持可用，未调用的兼容能力见文档。
"""
from .absorb import ExtractionPlan, build_plan, dialogue_of, recover_parents, worth_now
from .buffer import Buffer
from .calls import log_call
from .compress import build_compress_prompt, parse_compress
from .extract import build_prompt, ExtractionParseError, parse_response, parse_response_checked, filter_duplicates
from .importance import (
    MIN_IMPORTANCE_SCORE, TopicImportance, score_topic, rank_topics,
    select_important_topics, select_ranked_topics,
)
from .model import ProviderChatModel

__all__ = [
    "ExtractionPlan", "build_plan", "dialogue_of", "recover_parents", "worth_now", "Buffer",
    "log_call", "build_compress_prompt", "parse_compress", "build_prompt", "ExtractionParseError",
    "parse_response", "parse_response_checked", "filter_duplicates", "MIN_IMPORTANCE_SCORE",
    "TopicImportance", "score_topic", "rank_topics", "select_important_topics", "select_ranked_topics",
    "ProviderChatModel",
]
