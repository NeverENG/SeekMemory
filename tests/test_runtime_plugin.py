"""Production composition path for the AstrBot runtime worker."""

from __future__ import annotations

import logging
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

# Importing the composition module must not require a live AstrBot install.
astrbot = types.ModuleType("astrbot")
api = types.ModuleType("astrbot.api")
api.logger = logging.getLogger("seekmemory-test")
api.star = SimpleNamespace(Context=object, Star=object)
event = types.ModuleType("astrbot.api.event")
event.AstrMessageEvent = object
event.filter = SimpleNamespace(
    EventMessageType=SimpleNamespace(ALL="all")
)
core = types.ModuleType("astrbot.core")
utils = types.ModuleType("astrbot.core.utils")
utils_path = types.ModuleType("astrbot.core.utils.astrbot_path")
utils_path.get_astrbot_plugin_data_path = lambda: str(ROOT / "data")
sys.modules.update({
    "astrbot": astrbot,
    "astrbot.api": api,
    "astrbot.api.event": event,
    "astrbot.core": core,
    "astrbot.core.utils": utils,
    "astrbot.core.utils.astrbot_path": utils_path,
})

import importlib  # noqa: E402
AstrBotPlugin = importlib.import_module(
    f"{ROOT.name}.adapters.astrbot_plugin"
).AstrBotPlugin


class _Sources:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def latest_user_source(self, session_id):
        self.calls.append(session_id)
        return self.row


class RuntimePluginContextTest(unittest.TestCase):
    def test_make_run_context_maps_source_event_and_receipt_time(self):
        plugin = object.__new__(AstrBotPlugin)
        plugin._self_id = "bot-1"
        plugin.store = SimpleNamespace(
            sources=_Sources({
                "id": "s1",
                "text": "hello",
                "at": "1970-01-01T00:00:10+00:00",
            })
        )

        context = plugin._make_run_context("umo:1", 123.5)

        self.assertEqual(context.session_id, "umo:1")
        self.assertEqual(context.text, "hello")
        self.assertEqual(context.source_id, "s1")
        self.assertEqual(context.bot_id, "bot-1")
        self.assertEqual(context.event_time, 10.0)
        self.assertEqual(context.received_at, 123.5)


if __name__ == "__main__":
    unittest.main()
