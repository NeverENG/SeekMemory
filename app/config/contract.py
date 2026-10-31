"""Versioned policy manifest and advisory configuration diagnostics.

The profiles are documented presets, not an implicit runtime policy engine.
No host configuration is rewritten or activated by this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .catalog import FIELDS
from .defaults import DEFAULTS

CONFIG_VERSION = 1
# No previously released key has been renamed; aliases are introduced only
# alongside a future explicit migration decision.
ALIASES: Mapping[str, str] = MappingProxyType({})


@dataclass(frozen=True)
class ConfigProfile:
    id: str
    description: str
    overrides: Mapping[str, object]


PROFILES: Mapping[str, ConfigProfile] = MappingProxyType({
    "quiet": ConfigProfile("quiet", "Smaller recall context / 更少召回上下文", MappingProxyType({
        "recall_k": 4, "budget_chars": 400,
    })),
    "balanced": ConfigProfile("balanced", "Existing defaults / 既有默认", MappingProxyType({})),
    "engaged": ConfigProfile("engaged", "Larger recall context / 更大召回上下文", MappingProxyType({
        "recall_k": 10, "budget_chars": 800,
    })),
    "developer": ConfigProfile("developer", "Content-free diagnostic counts / 无正文诊断计数", MappingProxyType({
        "debug_log": True,
    })),
})


@dataclass(frozen=True)
class PolicyDependency:
    trigger: str
    value: object
    requires: str
    required_value: object


DEPENDENCIES: tuple[PolicyDependency, ...] = (
    PolicyDependency("proactive_enabled", True, "runtime_gate_enabled", True),
    PolicyDependency("relationship_mode", "enforce", "runtime_gate_enabled", True),
)
# No pair of existing keys is intrinsically forbidden; the above combinations
# are allowed but ineffective without their dependency.
CONFLICTS: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class ConfigWarning:
    code: str
    key: str
    message: str


def inspect_overrides(overrides: Mapping[str, object]) -> tuple[ConfigWarning, ...]:
    """Report invalid or inert options; never modify input or runtime behavior."""
    warnings: list[ConfigWarning] = []

    def warn(code: str, key: str, message: str) -> None:
        warnings.append(ConfigWarning(code, key, message))

    for key, value in overrides.items():
        if key == "config_version":
            if type(value) is not int or value != CONFIG_VERSION:
                warn("unsupported_version", key, "Only manifest version 1 is defined")
            continue
        if key == "config_profile":
            if not isinstance(value, str) or value not in PROFILES:
                warn("unknown_profile", key, "Unknown configuration profile")
            else:
                warn("profile_not_applied", key, "Profiles are descriptive in version 1")
            continue
        field = FIELDS.get(key)
        if field is None:
            warn("unknown_key", key, "Key is not in the SeekMemory contract")
            continue
        if value is None:
            continue  # Legacy None means use the existing default.
        if field.kind is bool:
            valid_type = type(value) is bool
        elif field.kind is float:
            valid_type = type(value) in (float, int)
        else:
            valid_type = type(value) is field.kind
        if not valid_type:
            warn("invalid_type", key, "Option has the wrong value type")
            continue
        if field.choices and value not in field.choices:
            warn("invalid_choice", key, "Option is not an allowed mode")
        if field.minimum is not None and (not math.isfinite(value) or value < field.minimum):
            warn("out_of_range", key, "Option is below its allowed minimum")
        if field.maximum is not None and (not math.isfinite(value) or value > field.maximum):
            warn("out_of_range", key, "Option exceeds its allowed maximum")

    # These are advisory: some combinations intentionally leave a setting inert.
    for dependency in DEPENDENCIES:
        if (overrides.get(dependency.trigger, DEFAULTS[dependency.trigger]) == dependency.value
                and overrides.get(dependency.requires, DEFAULTS[dependency.requires]) != dependency.required_value):
            warn("requires_runtime_gate", dependency.trigger,
                 "Option is inactive without its required runtime gate")
    if overrides.get("runtime_gate_enabled", DEFAULTS["runtime_gate_enabled"]) is False:
        if "runtime_wait_seconds" in overrides:
            warn("inactive_override", "runtime_wait_seconds", "Wait has no effect while the runtime gate is off")
    if overrides.get("attention_policy_enabled") is False and "attention_followup_rounds" in overrides:
        warn("inactive_override", "attention_followup_rounds", "Follow-up rounds are inactive with attention disabled")
    return tuple(warnings)
