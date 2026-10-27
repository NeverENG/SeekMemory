"""Typed bundle of application services.

This is data only: no lookup, registration or lifecycle management.
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
from .import_service import ImportService
from .maintenance_service import MaintenanceService
from .management_service import ManagementService
from .recall_service import RecallService
from .status_service import StatusService


@dataclass(frozen=True)
class ServiceCollection:
    access_service: AccessService
    recall_service: RecallService
    ingest_service: IngestService
    import_service: ImportService | None
    capacity_service: CapacityService
    maintenance_service: MaintenanceService
    management_service: ManagementService
    status_service: StatusService
    background_service: BackgroundService
    runtime: AgentRuntime
    runtime_worker: RuntimeWorker
