"""Required maintenance capabilities; reuse existing repository/cache declarations.

维护所需外部能力，复用既有仓储及缓存声明，不实现写入或管理资源。
"""
try:
    from ..app.ports import ArtifactCache, ArtifactStore, SourceStore
except ImportError:
    from app.ports import ArtifactCache, ArtifactStore, SourceStore

__all__ = ["ArtifactCache", "ArtifactStore", "SourceStore"]
