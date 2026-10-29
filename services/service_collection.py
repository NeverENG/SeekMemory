"""Bundle constructed services as immutable data; no registration or lifecycle work.

以不可变数据汇集已构造的服务，不注册服务或执行生命周期操作。
"""

from __future__ import annotations

from dataclasses import dataclass

try:
    from ..app.runtime import AgentRuntime, RuntimeWorker
except ImportError:
    from app.runtime import AgentRuntime, RuntimeWorker
from .access_service import AccessService
from .background_service import BackgroundService
from .capacity_service import CapacityService
from .ingest_service import IngestService
from .maintenance_service import MaintenanceService
from .management_service import ManagementService
from .recall_service import RecallService
from .status_service import StatusService


@dataclass(frozen=True)
class ServiceCollection:
    """Bundle constructed services without registry or lifecycle behavior / 汇集已构造的服务，不提供注册或生命周期行为。"""
    access_service: AccessService
    recall_service: RecallService
    ingest_service: IngestService
    capacity_service: CapacityService
    maintenance_service: MaintenanceService
    management_service: ManagementService
    status_service: StatusService
    background_service: BackgroundService
    runtime: AgentRuntime
    runtime_worker: RuntimeWorker
