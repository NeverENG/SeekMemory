"""Runtime facade for input, state, execution and write-back.

输入、状态、执行与写回的运行时入口；资源由组装方管理。
"""

from __future__ import annotations

import datetime
from typing import Callable

from .contracts import (
    ActionKind,
    ActionRequest,
    MemoryContext,
    MemoryContextPort,
    MemoryContextRequest,
    MessageSender,
    ProactiveDecision,
    ModelGateway,
    RunContext,
    AttentionDecision,
    RunDecision,
    RunResult,
    RuntimeInput,
    SessionState,
    UserRunReceipt,
    SessionStateStore,
    TraceSink,
    WakeAction,
)
from .actions import ActionExecutor
from .recorder import RecordedReply, RunRecorder
from .attention import DefaultAttentionPolicy
from .topics import TopicCandidate
from .writeback import DeliveryReceipt, DeliveryWritebacks
from .episode import normalize_tool_calls

from . import transitions
from .transitions import MAX_FOLLOWUP_SPEAKERS
from .dispatch import Dispatch, StateOperations, build_context, save_state


class AgentRuntime:
    """Keep caller-facing input, state and execution methods; internal dispatch owns no facade reference.

    保留对外输入、状态及执行方法，内部执行不持有整个入口对象。
    """

    def __init__(
        self,
        store: SessionStateStore,
        policy: DefaultAttentionPolicy | None = None,
        trace: TraceSink | None = None,
        clock: Callable[[], float] | None = None,
        memory_context: MemoryContextPort | None = None,
        wait_seconds: float = 0.0,
        model_gateway: ModelGateway | None = None,
        action_executor: ActionExecutor | None = None,
        message_sender: MessageSender | None = None,
        recorder: RunRecorder | None = None,
    ) -> None:
        self.store = store
        self.policy = policy or DefaultAttentionPolicy()
        self.trace = trace
        self.clock = clock or (lambda: 0.0)
        self.memory_context = memory_context
        self.wait_seconds = max(0.0, float(wait_seconds))
        self.model_gateway = model_gateway
        self.action_executor = action_executor
        self.message_sender = message_sender
        self.recorder = recorder
        self._writebacks = DeliveryWritebacks()

    def build_context(self, event: RuntimeInput, *, now: float | None = None,
                      reason: str = "inbound") -> MemoryContext:
        """Build read-only memory context / 构建只读记忆上下文。"""
        moment = self.clock() if now is None else float(now)
        return build_context(self.memory_context, event, moment, reason)

    def _save(self, state: SessionState) -> None:
        save_state(self.store, state)

    async def _send_text(self, session_id: str, text: str, *, run_id: str, callback_key: str) -> bool:
        return await self._dispatcher()._send_text(session_id, text, run_id=run_id, callback_key=callback_key)

    def observe(self, event: RuntimeInput, *, now: float | None = None) -> RunDecision:
        """Evaluate a non-stale event and persist the decision / 判断非过期事件并保存决策。"""
        moment = self.clock() if now is None else float(now)
        state = self.store.get(event.session_id)
        event_time = float(event.event_time or 0.0)
        if event_time > 0 and state.last_event_at > event_time:
            if self.trace is not None:
                self._trace("runtime", "stale_event", {
                    "event_time": event_time, "last_event_at": state.last_event_at,
                })
            return RunDecision(WakeAction.IGNORE, "stale_event")
        state = transitions.observe_event(state, event, moment)
        decision = self.policy.evaluate(event, state, moment)
        state = transitions.apply_attention(state, decision, moment, self.wait_seconds)
        self._save(state)
        result = decision.runtime_decision()
        if self.trace is not None:
            self._trace("runtime", result.action.value, {
                "reason": result.reason, "unread": state.unread_count,
                "ignored_streak": state.ignored_streak,
            })
        return result

    def accept_user(
        self,
        event: RuntimeInput,
        *,
        event_id: str = "",
        deferred: bool = False,
        now: float | None = None,
        decision: RunDecision | None = None,
    ) -> UserRunReceipt:
        """Record user evidence and projection, then evaluate attention; return the accepted read cursor.

        记录用户证据及投影后判断注意力，返回接收时的已读确认位置。
        """
        recorded = None
        if self.recorder is not None:
            seen_at = event.event_time or event.received_at
            at = (
                datetime.datetime.fromtimestamp(
                    float(seen_at), datetime.timezone.utc
                ).isoformat(timespec="seconds")
                if float(seen_at or 0.0) > 0
                else ""
            )
            recorded = self.recorder.record_user(
                session_id=event.session_id,
                text=event.text,
                speaker_id=event.speaker_id,
                event_id=event_id,
                at=at,
                deferred=deferred,
            )
        if decision is None:
            decision = self.observe(event, now=now)
        return UserRunReceipt(
            decision=decision,
            source_id=recorded.source_id if recorded is not None else "",
            turn_id=recorded.turn_id if recorded is not None else "",
            read_through_seq=(
                None if decision.reason == "stale_event"
                else self.store.get(event.session_id).last_unread_seq
            ),
        )

    def record_reply(
        self,
        *,
        run_id: str,
        session_id: str,
        text: str,
        speaker_id: str,
        turn_id: str = "",
        reply_to: str = "",
        at: str = "",
        recall_ids=(),
    ) -> RecordedReply | None:
        """Write assistant stages through the single recorder / 通过唯一记录器写入助手各阶段。"""
        if self.recorder is None:
            return None
        try:
            return self.recorder.record_reply(
                run_id=run_id, session_id=session_id, text=text, speaker_id=speaker_id,
                turn_id=turn_id, reply_to=reply_to, at=at, recall_ids=recall_ids,
            )
        except Exception:
            # Bind host delivery to the prepared ID even when persistence failed.
            # 持久写入失败时仍把宿主交付关联到已准备编号。
            prepared = getattr(self.recorder, "prepared_reply", None)
            reply = prepared(run_id) if callable(prepared) else None
            if reply is None:
                raise
            return reply

    def record_delivery(
        self,
        *,
        run_id: str,
        session_id: str,
        decision: str,
        reason: str,
        response_chars: int = 0,
        tool_calls=(),
        user_source_id: str = "",
        assistant_source_id: str = "",
        read_through_seq: int | None = None,
        now: float | None = None,
    ) -> None:
        """Retain confirmed delivery before state/audit writes; failures remain retryable / 状态及审计写入前保留已确认交付，失败可补写。"""
        moment = self.clock() if now is None else float(now)
        if self._writebacks.completed(session_id, run_id) is not None:
            return
        self._writebacks.remember(DeliveryReceipt(
            run_id=run_id, session_id=session_id, moment=moment, mode="normal",
            decision=decision, reason=reason, response_chars=response_chars,
            tool_calls=normalize_tool_calls(tool_calls), user_source_id=user_source_id,
            assistant_source_id=assistant_source_id, read_through_seq=read_through_seq,
        ))
        self._writebacks.retry(self.store, self.recorder, session_id)

    def record_error(
        self,
        *,
        run_id: str,
        session_id: str,
        decision: str,
        reason: str,
        error: object = "",
        user_source_id: str = "",
        assistant_source_id: str = "",
    ) -> None:
        """Write safe normal-run failure metadata through the recorder / 通过记录器写入安全的普通运行失败信息。"""
        if self.recorder is None:
            return
        self.recorder.record_error(
            run_id=run_id,
            session_id=session_id,
            decision=decision,
            reason=reason,
            error=error,
            user_source_id=user_source_id,
            assistant_source_id=assistant_source_id,
        )

    async def dispatch_deferred(self, context: RunContext, *, now: float | None = None,
                                max_attempts: int = 3, base_seconds: float = 2.0) -> RunResult:
        """Execute one deferred run through injected ports / 通过注入端口执行一次延迟回复。"""
        pending = self._retry_before_dispatch(context)
        if pending is not None:
            return pending
        return await self._dispatcher().dispatch_deferred(context, now=now, max_attempts=max_attempts,
                                                           base_seconds=base_seconds)

    async def dispatch_proactive(self, context: RunContext, decision: ProactiveDecision, *,
                                 topic: TopicCandidate | None = None, now: float | None = None) -> RunResult:
        """Execute one proactive run with its own policy / 按主动策略执行一次主动发言。"""
        pending = self._retry_before_dispatch(context)
        if pending is not None:
            return pending
        return await self._dispatcher().dispatch_proactive(context, decision, topic=topic, now=now)

    def schedule_proactive(self, session_id: str, delay_seconds: float, *, now: float | None = None) -> SessionState:
        """Persist an explicit proactive due time / 保存明确的主动发言时间。"""
        moment = self.clock() if now is None else float(now)
        return StateOperations(self.store).apply(session_id, transitions.schedule_proactive, delay_seconds, moment)

    def clear_proactive(self, session_id: str) -> SessionState:
        """Cancel the proactive marker / 取消主动发言标记。"""
        return StateOperations(self.store).apply(session_id, transitions.clear_proactive)

    def clear_wait(self, session_id: str, now: float | None = None) -> SessionState:
        """Clear wait/retry deadlines / 清理等待和重试期限。"""
        moment = self.clock() if now is None else now
        return StateOperations(self.store).apply(session_id, transitions.clear_wait, moment)

    def claim_dispatch(self, session_id: str, source_id: str, now: float | None = None) -> int:
        """Persist the attempt before any await / 在异步执行之前保存尝试次数。"""
        moment = self.clock() if now is None else now
        return StateOperations(self.store).apply(session_id, transitions.claim_dispatch, source_id, moment).dispatch_attempts

    def schedule_retry(self, session_id: str, now: float, attempts: int,
                       max_attempts: int = 3, base_seconds: float = 2.0,
                       cap_seconds: float = 60.0, claimed: SessionState | None = None) -> SessionState:
        """Retry old work without replacing newer deadlines / 重试旧任务，不替换新期限。"""
        return StateOperations(self.store).apply(session_id, transitions.schedule_retry, now, attempts,
            max_attempts=max_attempts, base_seconds=base_seconds, cap_seconds=cap_seconds, claimed=claimed)

    @staticmethod
    def _pending_changed(state: SessionState, claimed: SessionState) -> bool:
        return transitions.pending_changed(state, claimed)

    def mark_delivered(self, session_id: str, now: float | None = None, *,
                       claimed: SessionState | None = None, read_through_seq: int | None = None) -> SessionState:
        """Acknowledge delivered input without clearing newer work / 确认已交付输入，不清除新任务。"""
        moment = self.clock() if now is None else now
        return StateOperations(self.store).apply(session_id, transitions.mark_delivered, moment,
                                                 claimed=claimed, read_through_seq=read_through_seq)

    def _dispatcher(self) -> Dispatch:
        """Bind current ports without exposing this facade / 绑定当前端口，不传递整个入口对象。"""
        return Dispatch(store=self.store, clock=self.clock, memory_context=self.memory_context,
                        model_gateway=self.model_gateway, action_executor=self.action_executor,
                        message_sender=self.message_sender, recorder=self.recorder, trace=self.trace,
                        writebacks=self._writebacks)

    def retry_writebacks(self) -> int:
        """Retry writes without model/send access, including with speaking disabled.

        只补写，不调用模型或发送；关闭后台发言时仍可调用，返回完成项数。
        """
        completed = 0
        retry = getattr(self.recorder, "retry_pending", None)
        if callable(retry):
            completed += retry()
        return completed + self._writebacks.retry(self.store, self.recorder)

    def _retry_before_dispatch(self, context: RunContext) -> RunResult | None:
        """Finish old delivery before starting new background work / 后台新任务开始前补完旧交付。"""
        pending = self._writebacks.for_session(context.session_id)
        self.retry_writebacks()
        if pending is not None:
            return pending.result(self._writebacks.for_session(context.session_id) is not None)
        return self._writebacks.completed(context.session_id, context.run_id)

    def _trace(self, *args, **kwargs) -> None:
        """Keep diagnostic failures separate from state changes / 诊断失败与状态变化分开。"""
        try:
            if self.trace is not None:
                self.trace.record(*args, **kwargs)
        except Exception:
            pass
