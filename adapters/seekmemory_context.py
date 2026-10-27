"""Bridge the runtime MemoryContextPort to SeekMemory's recall pipeline."""

from __future__ import annotations

from typing import Callable

try:
    from ..app.runtime.contracts import MemoryContext, MemoryContextRequest
except ImportError:
    from app.runtime.contracts import MemoryContext, MemoryContextRequest


class SeekMemoryContextAdapter:
    def __init__(self, build: Callable[[MemoryContextRequest], MemoryContext]) -> None:
        self._build = build

    def build_context(self, request: MemoryContextRequest) -> MemoryContext:
        return self._build(request)
