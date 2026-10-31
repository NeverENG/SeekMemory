"""Typed Runtime scheduling options, independent of the chat host."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .defaults import DEFAULTS


@dataclass(frozen=True)
class RuntimeSettings:
    gate_enabled: bool
    wait_seconds: int
    tick_seconds: float
    dispatch_max_attempts: int
    dispatch_backoff_seconds: float

    @classmethod
    def read(cls, get: Callable[[str, object], object]) -> RuntimeSettings:
        """Snapshot current settings; callers can read again for live worker values."""
        return cls(
            gate_enabled=bool(get("runtime_gate_enabled", DEFAULTS["runtime_gate_enabled"])),
            wait_seconds=int(get("runtime_wait_seconds", DEFAULTS["runtime_wait_seconds"])),
            tick_seconds=float(get("runtime_tick_seconds", DEFAULTS["runtime_tick_seconds"])),
            dispatch_max_attempts=int(get("runtime_dispatch_max_attempts", DEFAULTS["runtime_dispatch_max_attempts"])),
            dispatch_backoff_seconds=float(get("runtime_dispatch_backoff_seconds", DEFAULTS["runtime_dispatch_backoff_seconds"])),
        )

    @property
    def effective_wait_seconds(self) -> int:
        return self.wait_seconds if self.gate_enabled else 0
