"""Register callbacks with existing module, name, priority and order; create no resources.

按既有模块、名称、优先级和顺序注册回调，不创建资源。
"""
from __future__ import annotations

from astrbot.api.event import filter

def _register(main_module: str, name: str, decorator, component: str = "hooks"):
    """Build one callback with stable plugin module/name metadata / 构造具有稳定插件模块及名称元数据的一个回调。"""
    async def handler(self, *args, **kwargs):
        return await getattr(getattr(self, component), name)(*args, **kwargs)

    handler.__module__ = main_module
    handler.__qualname__ = f"Main.{name}"
    # AstrBot keys handlers by module/name; every closure needs its own stable name.
    # AstrBot 按模块及名称识别处理器，每个闭包都需要自身稳定名称。
    handler.__name__ = name
    return decorator(handler)


def build_astrbot_hooks(main_module: str) -> dict:
    """Return the existing ordered hook registrations for the real plugin module / 为真实插件模块返回既有顺序的钩子注册。"""
    return {
        "inject_memory": _register(
            main_module, "inject_memory", filter.on_llm_request()
        ),
        "buffer_message": _register(
            main_module,
            "buffer_message",
            filter.event_message_type(filter.EventMessageType.ALL),
        ),
        "capture_reply": _register(
            main_module, "capture_reply", filter.on_llm_response()
        ),
        "record_delivery": _register(
            main_module, "record_delivery", filter.after_message_sent()
        ),
        "observe_agent_begin": _register(
            main_module, "observe_agent_begin", filter.on_agent_begin()
        ),
        "observe_agent_done": _register(
            main_module, "observe_agent_done", filter.on_agent_done()
        ),
        "observe_tool": _register(
            main_module, "observe_tool", filter.on_using_llm_tool()
        ),
        "observe_tool_result": _register(
            main_module, "observe_tool_result", filter.on_llm_tool_respond()
        ),
        "start_jobs": _register(
            main_module, "start_jobs", filter.on_astrbot_loaded()
        ),
        "attention_gate": _register(
            main_module,
            "attention_gate",
            filter.event_message_type(filter.EventMessageType.ALL, priority=9999),
            component="attention",
        ),
    }
