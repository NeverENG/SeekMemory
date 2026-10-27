"""SeekMemory AstrBot entrypoint: explicit composition and lifecycle."""

from astrbot.api import star

from .adapters.astrbot_hooks import build_astrbot_hooks
from .adapters.astrbot_plugin import AstrBotPlugin

_HOOKS = build_astrbot_hooks(__name__)


class Main(AstrBotPlugin, star.Star):
    """Thin host entrypoint; all business behavior lives in services."""

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
    inject_scene_hints = _HOOKS["inject_scene_hints"]

    def __init__(self, context, config: dict | None = None) -> None:
        super().__init__(context, config)

    async def initialize(self) -> None:
        await self.start_jobs()

    async def terminate(self) -> None:
        await self.stop()
