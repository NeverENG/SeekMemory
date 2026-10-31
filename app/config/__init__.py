"""Host-neutral configuration input for SeekMemory application policies."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .catalog import FIELDS, ConfigField
from .defaults import DEFAULTS, GROUPS
from .runtime import RuntimeSettings


class Settings:
    """Read optional host overrides over SeekMemory-owned defaults.

    An empty input is a supported configuration. Preserve the legacy caller
    fallback for unknown keys and its coercion when a caller supplies one.
    """

    def __init__(self, overrides: Mapping[str, object] | None = None) -> None:
        self._overrides = overrides if overrides is not None else {}

    def get(self, key: str, default: Any = None) -> Any:
        fallback = DEFAULTS.get(key, default)
        try:
            value = self._overrides.get(key, fallback)
            if value is None:
                value = fallback
            return type(default)(value) if default is not None else value
        except Exception:
            return type(default)(fallback) if default is not None else fallback


__all__ = ["DEFAULTS", "GROUPS", "FIELDS", "ConfigField", "Settings", "RuntimeSettings"]
