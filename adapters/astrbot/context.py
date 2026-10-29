"""Bridge pure recall and explicit context recording through supplied callbacks.

通过给定回调转接纯召回与明确的上下文记录，不拥有宿主或记忆资源。
"""

from __future__ import annotations

from typing import Callable

try:
    from ...app.runtime.contracts import MemoryContext, MemoryContextRequest
except ImportError:
    from app.runtime.contracts import MemoryContext, MemoryContextRequest


class SeekMemoryContextAdapter:
    """Forward narrow context callbacks / 转发窄上下文回调。"""

    def __init__(self, build: Callable[[MemoryContextRequest], MemoryContext],
                 record: Callable[[MemoryContext], None] | None = None) -> None:
        self._build = build
        self._record = record

    def build_context(self, request: MemoryContextRequest) -> MemoryContext:
        """Read context without recording inclusion / 读取上下文，不记录包含情况。"""
        return self._build(request)

    def record_context_injection(self, context: MemoryContext) -> None:
        """Forward explicit context inclusion without rebuilding context / 转发明确上下文包含情况，不重新查询。"""
        if self._record is not None:
            self._record(context)
