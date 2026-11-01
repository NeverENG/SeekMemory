"""Check reply decisions through the real AstrBot default processing stage.

通过真实 AstrBot 默认处理阶段检查回复决策，仅替换模型边界。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.astrbot.runtime import AstrBotRuntimeAdapter
from app.runtime import RunDecision, WakeAction
from core.interaction_policy import InteractionGate

try:
    from astrbot.core.platform.astr_message_event import AstrMessageEvent
    from astrbot.core.pipeline.process_stage.stage import ProcessStage
except ImportError:
    ProcessStage = None


class ModelBoundary:
    """Observe default model dispatch without generating or sending content."""

    def __init__(self) -> None:
        self.invoked = False

    async def process(self, event):
        self.invoked = True
        yield None


@unittest.skipIf(ProcessStage is None, "AstrBot host is not installed")
class RuntimeGateHostTest(unittest.IsolatedAsyncioTestCase):
    async def dispatched(
        self, decision: RunDecision, *, enabled: bool = True, denied: bool = False,
        initial_stop: bool = False, awake: bool = True,
    ) -> bool:
        extras = {"activated_handlers": []}
        event = SimpleNamespace(
            call_llm=initial_stop, _has_send_oper=False,
            is_at_or_wake_command=awake, get_result=lambda: None,
            get_extra=lambda key, default=None: extras.get(key, default),
            set_extra=lambda key, value: extras.__setitem__(key, value),
        )
        event.should_call_llm = lambda value: AstrMessageEvent.should_call_llm(event, value)
        if denied:
            AstrBotRuntimeAdapter.bind_interaction(
                event, InteractionGate(enforced=True, allow_reply=False),
            )
        AstrBotRuntimeAdapter.apply_llm_gate(event, decision, enabled)
        stage = ProcessStage()
        stage.ctx = SimpleNamespace(astrbot_config={"provider_settings": {"enable": True}})
        stage.agent_sub_stage = ModelBoundary()
        async for _ in stage.process(event):
            pass
        return stage.agent_sub_stage.invoked

    async def test_reply_and_must_reply_dispatch_default_model(self) -> None:
        for decision in (
            RunDecision(WakeAction.REPLY, "direct"),
            RunDecision(WakeAction.WAIT, "required", must_reply=True),
        ):
            with self.subTest(decision=decision):
                self.assertTrue(await self.dispatched(decision))

    async def test_non_reply_actions_do_not_dispatch_default_model(self) -> None:
        for action in WakeAction:
            if action is WakeAction.REPLY:
                continue
            with self.subTest(action=action):
                self.assertFalse(await self.dispatched(RunDecision(action, "ambient")))

    async def test_relationship_denial_overrides_required_reply(self) -> None:
        decision = RunDecision(WakeAction.REPLY, "direct", must_reply=True)
        self.assertFalse(await self.dispatched(decision, denied=True))

    async def test_disabled_gate_preserves_both_host_flags(self) -> None:
        decision = RunDecision(WakeAction.REPLY, "direct", must_reply=True)
        for initial_stop in (False, True):
            with self.subTest(initial_stop=initial_stop):
                self.assertEqual(
                    await self.dispatched(decision, enabled=False, denied=True,
                                          initial_stop=initial_stop),
                    not initial_stop,
                )

    async def test_reply_does_not_bypass_host_wake_requirement(self) -> None:
        self.assertFalse(await self.dispatched(
            RunDecision(WakeAction.REPLY, "direct"), awake=False,
        ))


if __name__ == "__main__":
    unittest.main()
