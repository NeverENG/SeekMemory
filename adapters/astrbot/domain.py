"""Explicit AstrBot integration exports; SDK-dependent imports are intentional.

明确 AstrBot 集成导出，此入口有意依赖 SDK；无 SDK 映射仍可从原文件单独导入。
"""
from .plugin import AstrBotPlugin
from .hooks import AstrBotHooks, build_astrbot_hooks
from .attention import AttentionHooks
from .actions import AstrBotActionPort
from .context import SeekMemoryContextAdapter
from .events import to_runtime_input, event_id
from .model import AstrBotModelGateway
from .runtime import AstrBotRuntimeAdapter
from .topics import AstrBotTopicSource
from .time import (
    utc8_time_hook, utc8_timestamp, AstrBotSourceView, AstrBotRunRecorder, AstrBotBuffer,
)

__all__ = [
    "AstrBotPlugin", "AstrBotHooks", "build_astrbot_hooks", "AttentionHooks", "AstrBotActionPort",
    "SeekMemoryContextAdapter", "to_runtime_input", "event_id", "AstrBotModelGateway",
    "AstrBotRuntimeAdapter", "AstrBotTopicSource", "utc8_time_hook", "utc8_timestamp",
    "AstrBotSourceView", "AstrBotRunRecorder", "AstrBotBuffer",
]
