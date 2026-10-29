"""Required recall capabilities; explicit existing protocol exports only.

召回所需的外部能力，仅明确导出现有协议；资源由组装方管理，不包含实现。
"""
try:
    from ..app.ports import ArtifactCache, ArtifactStore, SourceStore, Retriever
except ImportError:
    from app.ports import ArtifactCache, ArtifactStore, SourceStore, Retriever

__all__ = ["ArtifactCache", "ArtifactStore", "SourceStore", "Retriever"]
