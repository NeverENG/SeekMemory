"""Compatible service exports; see domain for provided entries and ports for dependencies.

兼容的服务导出；domain 列出对外入口，ports 列出外部依赖，此处不实现业务。
"""
from .domain import (
    AccessPolicy, AccessService, BackgroundService, CapacityService, IngestService,
    MaintenanceService, ManagementService, RecallService, ServiceCollection, StatusService, TreeService,
)
from .domain import __all__
