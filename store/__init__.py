"""Compatible repository composition exports; no SQL or resource creation here.

兼容的仓储组装导出，本入口不实现 SQL 或创建资源。
"""
try:
    from .domain import (
        Store, open_store, ArtifactRepository, SourceRepository, ExtractionRepository,
        LedgerRepository, RuntimeStateRepository, RuntimeEpisodeRepository, DreamRepository,
        StoreMetricsRepository,
    )
    from .sqlite import SqliteDatabase
except ImportError:  # Existing standalone mode / 保留已有的独立导入方式。
    from composition import (
        Store, open_store, ArtifactRepository, SourceRepository, ExtractionRepository,
        LedgerRepository, RuntimeStateRepository, RuntimeEpisodeRepository, DreamRepository,
        StoreMetricsRepository, SqliteDatabase,
    )

__all__ = ["Store", "open_store"]
