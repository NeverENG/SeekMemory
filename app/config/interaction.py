"""Host-neutral attention and proactive policy inputs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .defaults import DEFAULTS


@dataclass(frozen=True)
class AttentionSettings:
    policy_enabled: bool
    followup_rounds: int
    owner_always_reply: bool
    address_names: str

    @classmethod
    def read(cls, get: Callable[[str, object], object]) -> AttentionSettings:
        return cls(
            policy_enabled=bool(get("attention_policy_enabled", DEFAULTS["attention_policy_enabled"])),
            followup_rounds=int(get("attention_followup_rounds", DEFAULTS["attention_followup_rounds"])),
            owner_always_reply=bool(get("attention_owner_always_reply", DEFAULTS["attention_owner_always_reply"])),
            address_names=str(get("attention_address_names", DEFAULTS["attention_address_names"])),
        )


@dataclass(frozen=True)
class ProactiveSettings:
    enabled: bool
    idle_seconds: float

    @classmethod
    def read(cls, get: Callable[[str, object], object]) -> ProactiveSettings:
        return cls(
            enabled=bool(get("proactive_enabled", DEFAULTS["proactive_enabled"])),
            idle_seconds=float(get("proactive_idle_seconds", DEFAULTS["proactive_idle_seconds"])),
        )
