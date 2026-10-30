"""Host-neutral management dispatch; authentication belongs to HTTP adapters."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..services.management_service import ManagementService
from ..services.trace_query import query_traces

READ_ACTIONS = frozenset({
    "status", "records", "detail", "events", "traces", "graph", "impressions",
    "dream", "packs", "pack", "packArtwork", "packExport",
})
WRITE_ACTIONS = frozenset({
    "update", "rollbackPersona", "diagnose", "persona", "task", "cancel",
})


@dataclass(frozen=True)
class ApiResponse:
    status: int
    data: dict


def error(status: int, message: str) -> ApiResponse:
    """Use the same error envelope as the existing management contract."""
    return ApiResponse(status, {"status": "error", "message": message, "data": None})


class ConsoleApi:
    """Expose management use cases without host request objects or storage access."""

    def __init__(self, management: ManagementService, *,
                 status: Callable[[], dict], traces: Callable[[str], dict]) -> None:
        self.management = management
        self.status = status
        self.traces = traces

    def handle(self, action: str, method: str, query: dict[str, str],
               body: object = None) -> ApiResponse:
        """Validate transport inputs and map use-case failures to HTTP responses."""
        if action not in READ_ACTIONS | WRITE_ACTIONS:
            return error(404, "未知操作")
        if method != ("GET" if action in READ_ACTIONS else "POST"):
            return error(405, "请求方法不支持")
        try:
            if method == "GET":
                return ApiResponse(200, self._read(action, query))
            if not isinstance(body, dict):
                return error(400, "请求体必须为 JSON 对象")
            if action in {"task", "cancel"}:
                return error(503, "独立控制台未启用模型与后台维护任务")
            service = self.management
            if action == "update":
                return ApiResponse(200, {"id": service.update(body)})
            commands = {
                "persona": service.persona_action,
                "rollbackPersona": service.rollback_persona,
                "diagnose": service.diagnose,
            }
            return ApiResponse(200, commands[action](body))
        except LookupError:
            return error(404, "记忆或人格包不存在，请刷新列表")
        except ValueError as exc:
            if str(exc) in {"revision_conflict", "pack_changed"}:
                return error(409, "内容已被修改，请重新加载并核对后再提交")
            # Validation failures can contain user input; do not echo it to logs.
            return error(400, "请求参数无效，请检查字段和人格包格式")
        except Exception:
            return error(500, "操作失败，请检查本地数据与服务状态")

    def _read(self, action: str, query: dict[str, str]) -> dict:
        service = self.management
        if action == "status":
            return self.status()
        if action == "records":
            return {"records": service.catalog()}
        if action == "detail":
            return service.detail(query.get("id", ""))
        if action == "traces":
            return query_traces(self.traces, query)
        if action == "events":
            # This service does not run the host's lifecycle jobs.
            return {"events": [], "capacity": 500}
        if action == "graph":
            return service.graph()
        if action == "impressions":
            return service.impressions(offset=int(query.get("offset", "0")))
        if action == "dream":
            return service.dream_journal()
        if action == "packs":
            return service.pack_catalog(query.get("collection", "official"),
                                        int(query.get("offset", "0")))
        readers = {"pack": service.pack_detail, "packArtwork": service.pack_artwork,
                   "packExport": service.pack_export}
        return readers[action](query.get("reference", ""))
