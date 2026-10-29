"""Bind AstrBot hooks and lifecycle entry points; delegate resource ownership to AstrBotPlugin. / 绑定 AstrBot 钩子及生命周期入口，将资源归属委托 AstrBotPlugin。"""

from .adapters.astrbot.hooks import build_astrbot_hooks
from .adapters.astrbot.plugin import AstrBotPlugin

_HOOKS = build_astrbot_hooks(__name__)


class Main(AstrBotPlugin):
    """Expose explicit host hooks while services own business flows. / 提供明确宿主钩子，业务流程归服务所有。"""

    inject_memory = _HOOKS["inject_memory"]
    buffer_message = _HOOKS["buffer_message"]
    capture_reply = _HOOKS["capture_reply"]
    record_delivery = _HOOKS["record_delivery"]
    observe_agent_begin = _HOOKS["observe_agent_begin"]
    observe_agent_done = _HOOKS["observe_agent_done"]
    observe_tool = _HOOKS["observe_tool"]
    observe_tool_result = _HOOKS["observe_tool_result"]
    start_jobs = _HOOKS["start_jobs"]
    attention_gate = _HOOKS["attention_gate"]

    def __init__(self, context, config: dict | None = None) -> None:
        """Delegate injected host context and configuration to plugin composition. / 将注入的宿主上下文及配置委托插件组装。"""
        super().__init__(context, config)

    async def initialize(self) -> None:
        """Start the existing plugin lifecycle through the registered loaded hook. / 通过已注册加载钩子启动既有插件生命周期。"""
        await self.start_jobs()

    async def terminate(self) -> None:
        """Stop the plugin and let its resource owner finish cleanup. / 停止插件并由资源所有者完成清理。"""
        await self.stop()
