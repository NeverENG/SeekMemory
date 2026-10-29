"""Finite host dependencies used by AstrBot bindings; declarations only.

AstrBot 转接使用的有限宿主依赖，仅声明；组装方拥有服务、连接和任务生命周期。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from ...app.ports import ArtifactCache
    from ...app.runtime.actions import ActionExecutor
    from ...app.runtime.tools import ToolPolicy
    from ...app.runtime.tracing import RunTracer
    from ...services.service_collection import ServiceCollection
    from ...store.composition import Store
    from ...webui.journal import Journal
    from ...webui.trace import Trace
    from .time import AstrBotBuffer
    from .hooks import AstrBotHooks


class ProviderHost(Protocol):
    """Resolve existing model providers; lifecycle stays in the SDK.

    解析既有模型提供方，生命周期由 SDK 管理。
    """

    async def get_using_provider_async(self, session_id: str | None = None) -> Any:
        """Read the configured provider or return None / 读取已配置的提供方，或返回空。"""
        ...


class MessageHost(Protocol):
    """Execute host delivery without owning retry or audit rules.

    执行宿主交付，不负责重试或审计规则。
    """

    async def send_message(self, session_id: str, message: Any) -> Any:
        """Report host delivery; cancellation propagates / 报告宿主交付，取消向上传递。"""
        ...


class HookHost(Protocol):
    """Declare the exact shared host view used by callbacks.

    声明回调使用的明确共享宿主视图；钩子不再转发任意未知属性。
    """

    ready: bool
    services: ServiceCollection | None
    store: Store | None
    cache: ArtifactCache | None
    buffer: AstrBotBuffer | None
    journal: Journal | None
    trace: Trace | None
    run_tracer: RunTracer | None
    tool_policy: ToolPolicy | None
    action_executor: ActionExecutor | None
    relationship_policy: Any
    clock: Callable[[], float]
    owner_umo: str
    _last_runtime_prune_at: float
    _self_id: str
    hooks: AstrBotHooks

    def _c(self, key: str, default: Any) -> Any:
        """Read existing plugin configuration with its supplied fallback / 按给定回退读取既有插件配置。"""
        ...

    def _calls_path(self) -> str:
        """Read the content-free call log path beside the database / 读取数据库旁的无正文调用日志路径。"""
        ...

    def _admit_deferred(self) -> bool:
        """Ask the existing capacity service for deferred admission / 向既有容量服务请求延后接纳决策。"""
        ...

    async def start(self) -> None:
        """Serialize startup; clean partially created resources on failure/cancellation / 串行启动，失败或取消时清理部分创建的资源。"""
        ...


__all__ = ["ProviderHost", "MessageHost", "HookHost"]
