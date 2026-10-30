"""Correlate host events for diagnostics; never modify business decisions or own the store / 关联宿主事件以供诊断，不修改业务决策或管理存储。"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol
from uuid import uuid4

try:
    from ...core.domain.operations.trace import recall_data
except ImportError:
    from core.domain.operations.trace import recall_data


class TraceWriter(Protocol):
    """Injected diagnostic row persistence; separate from business audit / 注入的诊断行存储，与业务审计分开。"""
    def append(self, row: dict) -> None:
        """Append safe diagnostic metadata / 追加安全诊断信息。"""
        ...


@dataclass
class RunState:
    """Process-local event correlation and timing markers / 进程内事件关联及计时标记。"""
    id: str = field(default_factory=lambda: uuid4().hex)
    sequence: int = 0
    request_index: int = 0
    done: bool = False
    delivered: bool = False
    requested_at: float | None = None
    tools: dict[int, tuple[float | None, int]] = field(default_factory=dict)


class RunTracer:
    """Correlate host-shaped events and write diagnostics; failures never change behavior / 关联宿主形状事件并写诊断，失败不改变行为。"""
    def __init__(self, store: TraceWriter, *, clock=time.time) -> None:
        self.store = store
        self.clock = clock

    def _state(self, event) -> RunState:
        state = event.get_extra("_seekmemory_run_trace", None)
        if not isinstance(state, RunState):
            state = RunState()
            event.set_extra("_seekmemory_run_trace", state)
        return state

    def _record(self, state: RunState, name: str, status: str = "unknown", **values) -> None:
        state.sequence += 1
        self.store.append({"run_id": state.id, "sequence": state.sequence,
            "request_index": state.request_index,
            "at": datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(),
            "event": name, "status": status, **values})

    def run_id(self, event) -> str:
        """Read or create the event run ID; failure returns empty / 读取或创建事件运行编号，失败返回空。"""
        try:
            return self._state(event).id
        except Exception:
            return ""

    def begin(self, event) -> None:
        """Start correlation, replacing a completed run / 开始关联，已结束运行会被替换。"""
        try:
            state = self._state(event)
            if state.done:
                state = RunState()
                event.set_extra("_seekmemory_run_trace", state)
            self._record(state, "agent_begin", "running")
        except Exception:
            pass

    def request(self, event, info: dict | None, status: str = "ok") -> None:
        """Record a request with sanitized recall metadata and start timing / 记录包含规整召回信息的请求并开始计时。"""
        try:
            state = self._state(event)
            if state.done:
                state = RunState()
                event.set_extra("_seekmemory_run_trace", state)
            state.request_index += 1
            state.requested_at = self.clock()
            self._record(state, "llm_request", status,
                         recall=recall_data(info) if info is not None else None)
        except Exception:
            pass

    def response(self, event, status: str) -> None:
        """Record response status and elapsed time / 记录响应状态及耗时。"""
        try:
            state = self._state(event)
            elapsed = None if state.requested_at is None else max(0, (self.clock() - state.requested_at) * 1000)
            self._record(state, "llm_response", status, duration_ms=elapsed)
        except Exception:
            pass

    def done(self, event, status: str) -> None:
        """Record completion once and release tool timing entries / 记录一次结束并释放工具计时项。"""
        try:
            state = self._state(event)
            if not state.done:
                self._record(state, "agent_done", status)
                state.done = True
                state.tools.clear()
        except Exception:
            pass

    def delivered(self, event) -> None:
        """Record confirmed platform delivery once per correlated run / 每个关联运行记录一次已确认平台交付。"""
        try:
            state = event.get_extra("_seekmemory_run_trace", None)
            if isinstance(state, RunState) and not state.delivered:
                self._record(state, "message_sent", "ok")
                state.delivered = True
        except Exception:
            pass

    def tool_begin(self, event, tool) -> None:
        """Record tool name and timing without argument values / 记录工具名及计时，不保存参数值。"""
        try:
            state = self._state(event)
            name = str(getattr(tool, "name", ""))
            previous = state.tools.get(id(tool))
            # No host call ID: overlapping calls have no reliable duration.
            # 宿主没有调用编号，并发调用无法提供可靠时长。
            state.tools[id(tool)] = (self.clock(), 1) if previous is None else (None, previous[1] + 1)
            self._record(state, "tool_call", "running", tool=name)
        except Exception:
            pass

    def tool_end(self, event, tool) -> None:
        """Record tool completion; overlapping unknown calls have no duration / 记录工具结束，无法区分的并发调用不报告时长。"""
        try:
            state = self._state(event)
            start = state.tools.pop(id(tool), None)
            if start is not None and start[1] > 1:
                state.tools[id(tool)] = (None, start[1] - 1)
            duration = None if start is None or start[0] is None else max(0, (self.clock() - start[0]) * 1000)
            self._record(state, "tool_result", "unknown",
                         tool=str(getattr(tool, "name", "")), duration_ms=duration)
        except Exception:
            pass
