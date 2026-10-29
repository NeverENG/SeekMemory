"""Coordinate background execution through ports and pure state transitions.

通过端口及纯状态变化编排后台执行；不持有 AgentRuntime 或管理资源生命周期。
"""

from __future__ import annotations

import asyncio
import datetime
from dataclasses import replace
from typing import Callable

from . import transitions
from .contracts import (
    ActionKind, ActionRequest, MemoryContext, MemoryContextPort, MemoryContextRequest,
    MessageSender, ModelGateway, ProactiveDecision, RunContext, RunResult,
    RuntimeInput, SessionState, SessionStateStore, TraceSink,
)
from .actions import ActionExecutor
from .recorder import RunRecorder
from .topics import TopicCandidate
from .writeback import DeliveryReceipt, DeliveryWritebacks


def save_state(store: SessionStateStore, state: SessionState) -> None:
    """Persist the next revision of a detached state / 保存独立状态的下一版本。"""
    state.revision = max(0, int(state.revision or 0)) + 1
    store.put(state)


def build_context(port: MemoryContextPort | None, event: RuntimeInput,
                  moment: float, reason: str) -> MemoryContext:
    """Read context through the existing recall port / 通过已有召回端口读取上下文。"""
    if port is None:
        return MemoryContext()
    return port.build_context(MemoryContextRequest(
        session_id=event.session_id, query=event.text, speaker_id=event.speaker_id,
        private=event.private, event_time=event.event_time,
        received_at=event.received_at, now=moment, reason=reason,
    ))


class StateOperations:
    """Apply pure transitions to the injected store / 将纯状态变化保存到注入的存储。"""

    def __init__(self, store: SessionStateStore) -> None:
        self.store = store

    def apply(self, session_id: str, transition: Callable, *args, **kwargs) -> SessionState:
        """Read current state, compute and save its successor / 读取当前状态，计算并保存后继。"""
        state = self.store.get(session_id)
        updated = transition(state, *args, **kwargs)
        if updated is not state:
            save_state(self.store, updated)
        return updated


class Dispatch:
    """Own generation, delivery and their path-specific retries / 管理生成、交付及各路径的重试。"""

    def __init__(self, *, store: SessionStateStore, clock: Callable[[], float],
                 memory_context: MemoryContextPort | None, model_gateway: ModelGateway | None,
                 action_executor: ActionExecutor | None, message_sender: MessageSender | None,
                 recorder: RunRecorder | None, trace: TraceSink | None,
                 writebacks: DeliveryWritebacks) -> None:
        self.store = store
        self.clock = clock
        self.memory_context = memory_context
        self.model_gateway = model_gateway
        self.action_executor = action_executor
        self.message_sender = message_sender
        self.recorder = recorder
        self.trace = trace
        self.writebacks = writebacks
        self.states = StateOperations(store)

    def build_context(self, event: RuntimeInput, *, now: float, reason: str) -> MemoryContext:
        """Resolve context without knowing the host / 获取上下文，不依赖宿主。"""
        return build_context(self.memory_context, event, now, reason)

    def clear_wait(self, session_id: str, now: float | None) -> SessionState:
        return self.states.apply(session_id, transitions.clear_wait, self.clock() if now is None else now)

    def claim_dispatch(self, session_id: str, source_id: str, now: float) -> int:
        return self.states.apply(session_id, transitions.claim_dispatch, source_id, now).dispatch_attempts

    def schedule_retry(self, session_id: str, now: float, attempts: int, **kwargs) -> SessionState:
        return self.states.apply(session_id, transitions.schedule_retry, now, attempts, **kwargs)

    def mark_delivered(self, session_id: str, now: float, **kwargs) -> SessionState:
        return self.states.apply(session_id, transitions.mark_delivered, now, **kwargs)

    def _save(self, state: SessionState) -> None:
        save_state(self.store, state)


    async def _send_text(
        self, session_id: str, text: str, *, run_id: str, callback_key: str
    ) -> bool:
        if self.action_executor is not None:
            result = await self.action_executor.execute(
                ActionRequest(
                    session_id=session_id,
                    kind=ActionKind.SEND_TEXT,
                    text=text,
                ),
                run_id=run_id,
                callback_key=callback_key,
                at=self.clock(),
            )
            if not result.ok:
                raise RuntimeError(result.reason or "send_failed")
            return True
        if self.message_sender is not None:
            if not await self.message_sender.send(session_id, text):
                raise RuntimeError("send_failed")
            return True
        raise RuntimeError("runtime_port_missing")


    async def dispatch_deferred(
        self,
        context: RunContext,
        *,
        now: float | None = None,
        max_attempts: int = 3,
        base_seconds: float = 2.0,
    ) -> RunResult:
        """Claim, generate, send and record one deferred run.

        Host adapters provide the model and sender ports. The runtime owns the
        lifecycle and bounded retry; callers only map the latest Source into a
        RunContext.
        """
        session_id = str(context.session_id or "")
        source_id = str(context.source_id or "")
        text = str(context.text or "").strip()
        moment = self.clock() if now is None else float(now)
        run_id = str(context.run_id or "")
        state = self.store.get(session_id)
        wait_due = state.wait_until > 0 and state.wait_until <= moment
        retry_due = state.next_retry_at > 0 and state.next_retry_at <= moment
        if not (wait_due or retry_due):
            return RunResult(run_id, session_id, False, error="not_due")
        if state.wait_until > moment or (
            state.next_retry_at and state.next_retry_at > moment
        ):
            return RunResult(run_id, session_id, False, error="not_due")
        if not text:
            self.clear_wait(session_id, now)
            return RunResult(run_id, session_id, False, error="empty_source")
        if self.model_gateway is None or (
            self.action_executor is None and self.message_sender is None
        ):
            return RunResult(run_id, session_id, False, error="runtime_port_missing")
        if self.recorder is None:
            return RunResult(run_id, session_id, False, error="recorder_missing")
        if not run_id:
            run_id = self.recorder.new_run_id()

        if (state.last_dispatched_source_id == source_id
                and state.dispatch_attempts >= max(1, int(max_attempts))):
            self.schedule_retry(session_id, moment, state.dispatch_attempts,
                                max_attempts=max_attempts)
            return RunResult(run_id, session_id, False, error="dispatch_dead")
        attempts = self.claim_dispatch(session_id, source_id, moment)
        # Stores may return a live object. Keep a stable, run-local snapshot so
        # old pending markers can be distinguished from newer scheduled work.
        claimed = replace(self.store.get(session_id))
        runtime_input = RuntimeInput(
            session_id=session_id,
            text=text,
            private=False,
            event_time=context.event_time,
            received_at=context.received_at,
        )
        try:
            memory = self.build_context(
                runtime_input, now=moment, reason="deferred"
            )
            reply = await self.model_gateway.complete(
                session_id, text, memory.text or None
            )
            if not str(reply or "").strip():
                raise RuntimeError("empty_response")
            await self._send_text(
                session_id,
                reply,
                run_id=run_id,
                callback_key=f"deferred:{run_id}",
            )
        except (Exception, asyncio.CancelledError) as exc:
            try:
                # Refresh after awaited model/send work; explicit start time
                # remains a lower bound without an advancing injected clock.
                moment = max(moment, float(self.clock()))
                self.schedule_retry(
                    session_id,
                    moment,
                    attempts,
                    max_attempts=max_attempts,
                    base_seconds=base_seconds,
                    claimed=claimed,
                )
                self.recorder.record_deferred_error(
                    run_id=run_id,
                    session_id=session_id,
                    user_source_id=source_id,
                    error=exc,
                    at=datetime.datetime.fromtimestamp(
                        moment, datetime.timezone.utc
                    ).isoformat(timespec="seconds"),
                )
                if self.trace is not None:
                    self._trace(
                        "runtime",
                        "deferred_failed",
                        {"error": type(exc).__name__, "attempt": attempts},
                    )
            finally:
                if isinstance(exc, asyncio.CancelledError):
                    raise exc
            return RunResult(
                run_id,
                session_id,
                False,
                error=type(exc).__name__,
            )

        receipt = self.writebacks.remember(DeliveryReceipt(
            run_id=run_id, session_id=session_id, moment=moment, mode="deferred",
            decision="wait", reason="deferred_wait", text=reply,
            speaker_id=str(context.bot_id or "bot"), user_source_id=source_id,
            response_chars=len(str(reply).strip()), claimed=claimed,
            read_through_seq=claimed.last_unread_seq,
        ))
        # The receipt exists before reading a fallible clock or writing anything.
        # 在读取可能失败的时钟或执行写入前，交付凭据已经存在。
        try:
            receipt.moment = max(moment, float(self.clock()))
        except Exception:
            pass
        self.writebacks.retry(self.store, self.recorder, session_id)
        return receipt.result(self.writebacks.for_session(session_id) is not None)


    async def dispatch_proactive(
        self,
        context: RunContext,
        decision: ProactiveDecision,
        *,
        topic: TopicCandidate | None = None,
        now: float | None = None,
    ) -> RunResult:
        """Generate, send and record one due proactive turn."""
        moment = self.clock() if now is None else float(now)
        session_id = str(context.session_id or "")
        run_id = str(context.run_id or "")
        if not decision.should_speak:
            return RunResult(run_id, session_id, False, error="not_due")
        if self.model_gateway is None or (
            self.action_executor is None and self.message_sender is None
        ):
            return RunResult(run_id, session_id, False, error="runtime_port_missing")
        if self.recorder is None:
            return RunResult(run_id, session_id, False, error="recorder_missing")
        if not run_id:
            run_id = self.recorder.new_run_id()
        topic_text = str(topic.text if topic is not None else "").strip()
        runtime_input = RuntimeInput(
            session_id=session_id,
            text=topic_text or context.text,
            event_time=context.event_time,
            received_at=context.received_at,
        )
        claimed = transitions.snapshot(self.store.get(session_id))
        try:
            memory = self.build_context(runtime_input, now=moment, reason="proactive")
            prompt = (memory.text or "").strip()
            if topic_text:
                prompt = (
                    f"{prompt}\n\n主动由头（来自记忆）：{topic_text}"
                ).strip()
            reply = await self.model_gateway.complete(
                session_id, prompt or context.text, None
            )
            if not str(reply or "").strip():
                raise RuntimeError("empty_response")
            await self._send_text(
                session_id,
                reply,
                run_id=run_id,
                callback_key=f"proactive:{run_id}",
            )
        except (Exception, asyncio.CancelledError) as exc:
            state = transitions.snapshot(self.store.get(session_id))
            state.last_proactive_at = moment
            state.proactive_attempts = int(state.proactive_attempts or 0) + 1
            state.last_action = "wait"
            state.last_reason = decision.reason
            self._save(state)
            at = datetime.datetime.fromtimestamp(
                moment, datetime.timezone.utc
            ).isoformat(timespec="seconds")
            try:
                self.recorder.record_deferred_error(
                    run_id=run_id,
                    session_id=session_id,
                    user_source_id=context.source_id,
                    error=exc,
                    decision="proactive",
                    reason=decision.reason,
                    at=at,
                )
            finally:
                if isinstance(exc, asyncio.CancelledError):
                    raise exc
            return RunResult(run_id, session_id, False, error=type(exc).__name__)

        receipt = self.writebacks.remember(DeliveryReceipt(
            run_id=run_id, session_id=session_id, moment=moment, mode="proactive",
            decision="proactive", reason=decision.reason, text=reply,
            speaker_id=str(context.bot_id or "bot"), user_source_id=context.source_id,
            response_chars=len(str(reply).strip()), claimed=claimed,
        ))
        self.writebacks.retry(self.store, self.recorder, session_id)
        return receipt.result(self.writebacks.for_session(session_id) is not None)

    def _trace(self, *args, **kwargs) -> None:
        """Keep diagnostics outside business failure handling / 诊断不影响业务失败处理。"""
        try:
            if self.trace is not None:
                self.trace.record(*args, **kwargs)
        except Exception:
            pass
