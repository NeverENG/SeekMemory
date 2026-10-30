"""Policy and port moves retain compatible module and public-object identities."""

from __future__ import annotations

import importlib
import unittest


class RuntimePolicyLayoutTest(unittest.TestCase):
    def test_policy_modules_keep_legacy_import_identity(self) -> None:
        for name in ("attention", "proactive"):
            with self.subTest(name=name):
                legacy = importlib.import_module(f"app.runtime.{name}")
                owner = importlib.import_module(f"app.runtime.policy.{name}")
                self.assertIs(legacy, owner)

    def test_policy_exports_keep_public_identity(self) -> None:
        from app.runtime import DefaultAttentionPolicy, DefaultProactivePolicy
        from app.runtime.policy.attention import DefaultAttentionPolicy as AttentionOwner
        from app.runtime.policy.proactive import DefaultProactivePolicy as ProactiveOwner

        self.assertIs(DefaultAttentionPolicy, AttentionOwner)
        self.assertIs(DefaultProactivePolicy, ProactiveOwner)

    def test_runtime_port_moves_keep_legacy_contract_identity(self) -> None:
        from app.runtime.contracts import MemoryContext, MemoryContextPort, ModelGateway
        from app.runtime.contracts.context import MemoryContext as ContextOwner
        from app.runtime.contracts.ports import (
            MemoryContext as LegacyContext, MemoryContextPort as LegacyPort,
            ModelGateway as LegacyModel,
        )
        from app.runtime.port.capabilities import (
            MemoryContextPort as PortOwner, ModelGateway as ModelOwner,
        )

        self.assertIs(MemoryContext, ContextOwner)
        self.assertIs(MemoryContext, LegacyContext)
        self.assertIs(MemoryContextPort, PortOwner)
        self.assertIs(MemoryContextPort, LegacyPort)
        self.assertIs(ModelGateway, ModelOwner)
        self.assertIs(ModelGateway, LegacyModel)


if __name__ == "__main__":
    unittest.main()
