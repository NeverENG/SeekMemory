"""Coordinate host event callbacks over explicit bindings; own no memory algorithms or resource lifetimes.

通过明确依赖协调宿主事件回调，不拥有记忆算法或资源生命周期。
"""

from __future__ import annotations

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ...app.runtime.contracts import ActionKind, ActionRequest, ActionStatus
from ...app.runtime.tools import tool_result_failed
from ...perceive.calls import log_call
from .attention import AttentionHooks
from .runtime import AstrBotRuntimeAdapter
from .ports import HookHost


class AstrBotHooks:
    """Map host callbacks to declared services, runtime and diagnostic capabilities / 将宿主回调映射到声明的服务、运行时及诊断能力。"""

    def __init__(self, host: HookHost | None = None) -> None:
        self.host = host
        self.clock = getattr(host, "clock", None) or (lambda: 0.0)
        self._action_attempts: dict = {}

    @property
    def _bindings(self) -> HookHost:
        """Read only the declared host view; detached legacy tests bind fields locally.

        仅读取已声明宿主视图，独立的旧测试可在本地绑定字段；不转发任意属性。
        """
        return self.host if self.host is not None else self

    def reset(self) -> None:
        """Clear process-local callback correlations after host work has stopped.

        在宿主工作停止后清理进程内回调关联，避免重启使用上次运行的工具尝试。
        """
        self._action_attempts.clear()

    def _maybe_prune_runtime_episodes(self) -> None:
        """Run bounded audit cleanup at the existing minimum interval / 按既有最小间隔执行有数量上限的审计清理。"""
        if self._bindings.store is None:
            return
        now = self.clock()
        if now - self._bindings._last_runtime_prune_at < 60:
            return
        try:
            self._bindings.store.runtime_episodes.prune(
                retention_days=int(self._bindings._c("runtime_episode_retention_days", 30)),
                max_rows=int(self._bindings._c("runtime_episode_max_rows", 5000)),
            )
            self._bindings._last_runtime_prune_at = now
        except Exception:
            pass

    def _may_observe(self, event: AstrMessageEvent) -> bool:
        """Read existing observation permission; unavailable host state denies it / 读取既有观察权限，宿主状态不可用时拒绝。"""
        if not self._bindings.ready or self._bindings.services is None:
            return False
        return self._bindings.services.access_service.may_observe(
            str(getattr(event, "unified_msg_origin", "") or ""),
            str(event.get_sender_id()),
        )

    def _may_recall(self, event: AstrMessageEvent) -> bool:
        """Read existing recall permission after readiness checks / 检查就绪状态后读取既有召回权限。"""
        if not self._bindings.ready or self._bindings.services is None:
            return False
        return self._bindings.services.access_service.may_recall(
            str(getattr(event, "unified_msg_origin", "") or ""),
            str(event.get_sender_id()),
        )

    async def inject_memory(self, event: AstrMessageEvent, req) -> None:
        """Build disclosed context, attach it to the request, then explicitly record inclusion / 构造已披露上下文，附到请求后明确记录包含情况。"""
        trace_allowed = False
        trace_info = None
        trace_status = "unknown"
        try:
            if not self._may_recall(event):
                return
            trace_allowed = True
            if not self._bindings.ready or self._bindings.cache is None:
                return
            text = (event.message_str or "").strip()
            if not text:
                return

            umo = str(getattr(event, "unified_msg_origin", "") or "")
            policy = getattr(self._bindings, "tool_policy", None)
            removed_tools = ()
            if bool(self._bindings._c("runtime_tool_filter_enabled", False)) and policy is not None:
                removed_tools = policy.filter_tool_set(
                    getattr(req, "func_tool", None)
                )
            if removed_tools:
                self._bindings.trace.record(
                    "tool", "guard_removed",
                    {"count": len(removed_tools), "enforced": True},
                )
                self._bindings.journal.record(
                    "tool", "info", "runtime tool guard removed tools",
                    context={"removed": len(removed_tools), "enforced": True},
                )
            runtime_input = AstrBotRuntimeAdapter.from_event(
                event, text, umo, str(event.get_sender_id()),
                owner_id=getattr(self._bindings, "_owner_id", lambda: "")(),
                names=getattr(self._bindings, "_address_names", lambda: ())(),
                clock=self.clock,
            )
            context = self._bindings.services.runtime.build_context(runtime_input)
            block, info = context.text, context.info
            self._bindings.services.capacity_service.set_context_chars(len(block))
            log_call(self._bindings._calls_path(), umo, info)
            AstrBotRuntimeAdapter.set_recall_ids(
                event, info.get("final_ids", ())
            )
            self._bindings.journal.record(
                "recall",
                "info",
                "召回文本已组装",
                stage="assemble",
                context={key: info[key] for key in ("mode", "picked", "chars")},
            )
            relationship_policy = getattr(self._bindings, "relationship_policy", None)
            style_prompt = (
                relationship_policy.directive(
                    AstrBotRuntimeAdapter.interaction_gate(event)
                )
                if relationship_policy is not None
                else ""
            )
            if style_prompt:
                req.system_prompt = (req.system_prompt or "") + style_prompt
            if block:
                # Preserve the existing memory frame in the model request.
                # 在模型请求中保留既有记忆文本框架。
                framed = (
                    "\n\n【你的记忆】\n"
                    "下面是你自己记得的事，来自你的记忆库。自然带出来，别逐条复述，"
                    "也别说「根据记忆」。没有这一段，就说明你此刻没想起来。\n"
                    + block
                    + "\n"
                )
                req.system_prompt = (req.system_prompt or "") + framed
                self._bindings.services.runtime.record_context_injection(context)
                if self._bindings._c("debug_log", False):
                    logger.info(f"[seekmemory] 注入 {len(block)} 字")
            trace_info, trace_status = info, "ok"
        except Exception as e:  # noqa: BLE001
            trace_status = "error"
            self._bindings.journal.record("recall", "failed", "召回失败", error=e)
            logger.error(f"[seekmemory] 注入失败（不影响回复）：{type(e).__name__}")
        finally:
            if trace_allowed:
                self._bindings.run_tracer.request(event, trace_info, trace_status)

    async def buffer_message(self, event: AstrMessageEvent) -> None:
        """Map accepted input, save immutable evidence and bind the runtime receipt / 映射已接纳输入，保存不可变证据并绑定运行时回执。"""
        try:
            if not self._may_observe(event):
                return
            text = (event.message_str or "").strip()
            if not text or self._bindings.buffer is None:
                return
            umo = str(getattr(event, "unified_msg_origin", "") or "")
            sender = str(event.get_sender_id())
            deferred = self._bindings._admit_deferred()
            runtime_input = AstrBotRuntimeAdapter.from_event(
                event,
                text,
                umo,
                sender,
                owner_id=getattr(self._bindings, "_owner_id", lambda: "")(),
                names=getattr(self._bindings, "_address_names", lambda: ())(),
                clock=self.clock,
            )
            decision = AstrBotRuntimeAdapter.get_extra(
                event, "_seekmemory_attention_decision", None
            )
            receipt = self._bindings.services.runtime.accept_user(
                runtime_input,
                event_id=AstrBotRuntimeAdapter.event_id(event),
                deferred=deferred,
                decision=decision,
            )
            AstrBotRuntimeAdapter.set_extra(
                event, "_seekmemory_attention_decision", receipt.decision
            )
            if self._bindings.buffer.save_error:
                self._bindings.journal.record(
                    "capacity",
                    "warning",
                    "pending save failed",
                    context={"error": self._bindings.buffer.save_error},
                )
            try:
                self._bindings._self_id = str(event.get_self_id())
            except Exception:
                pass
            AstrBotRuntimeAdapter.bind_user(event, receipt)
            self._schedule_proactive(umo)
            AstrBotRuntimeAdapter.apply_decision(event, receipt.decision)
            relationship_policy = getattr(self._bindings, "relationship_policy", None)
            if relationship_policy is not None:
                gate = relationship_policy.decide(
                    runtime_input,
                    receipt.decision,
                    source_id=receipt.source_id,
                )
                AstrBotRuntimeAdapter.bind_interaction(event, gate)
                self._bindings.trace.record(
                    "relationship",
                    "enforced" if gate.enforced else "observed",
                    {
                        "would_allow_reply": gate.allow_reply,
                        "would_style": gate.style.value,
                        "policy_version": relationship_policy.version,
                    },
                )
                if gate.enforced and not gate.allow_reply:
                    self._bindings.services.runtime.clear_wait(umo)
            AstrBotRuntimeAdapter.apply_llm_gate(
                event,
                receipt.decision,
                bool(self._bindings._c("runtime_gate_enabled", False)),
            )
        except Exception:
            pass

    def _schedule_proactive(self, session_id: str) -> None:
        """Delegate enabled proactive scheduling to runtime / 将已启用主动调度委托给运行时。"""
        if not bool(self._bindings._c("proactive_enabled", False)):
            return
        try:
            delay = float(self._bindings._c("proactive_idle_seconds", 1800))
            schedule = getattr(self._bindings.services.runtime, "schedule_proactive", None)
            if callable(schedule):
                schedule(session_id, delay, now=self.clock())
        except Exception:  # noqa: BLE001 - Isolate optional scheduling / 隔离可选调度。
            pass

    def _begin_send_action(self, event, session_id: str, run_id: str, turn_id: str) -> None:
        """Record a send attempt without including message text in audit / 记录发送尝试，不在审计中包含消息正文。"""
        executor = getattr(self._bindings, "action_executor", None)
        if executor is None:
            return
        try:
            record = executor.begin(
                ActionRequest(
                    session_id=session_id,
                    kind=ActionKind.SEND_TEXT,
                    text="",
                ),
                run_id=run_id,
                callback_key=f"send:{turn_id or run_id}",
                at=self.clock(),
            )
            AstrBotRuntimeAdapter.set_extra(
                event, "_seekmemory_send_action", record
            )
        except Exception:  # noqa: BLE001 - Audit cannot block replies / 审计不能阻塞回复。
            pass

    def _finish_send_action(self, event, status: ActionStatus, reason: str = "") -> None:
        """Record the observed send terminal status using its existing action receipt / 使用既有动作回执记录观察到的发送终态。"""
        executor = getattr(self._bindings, "action_executor", None)
        if executor is None:
            return
        try:
            record = AstrBotRuntimeAdapter.get_extra(
                event, "_seekmemory_send_action", None
            )
            if record is None:
                return
            executor.finish(record, status, at=self.clock(), reason=reason)
            AstrBotRuntimeAdapter.set_extra(event, "_seekmemory_send_action", None)
        except Exception:  # noqa: BLE001
            pass

    async def capture_reply(self, event: AstrMessageEvent, response) -> None:
        """Record a successful assistant response and correlate its pending send attempt / 记录成功助手响应，并关联其待发送尝试。"""
        try:
            if self._may_observe(event):
                self._bindings.run_tracer.response(
                    event,
                    "error" if getattr(response, "role", "") == "err" else "ok",
                )
            if not self._may_observe(event) or self._bindings.store is None:
                return
            if str(getattr(response, "role", "assistant")) == "err":
                return
            text = str(getattr(response, "completion_text", "") or "").strip()
            if not text:
                return
            reply = self._bindings.services.runtime.record_reply(
                run_id=self._bindings.run_tracer.run_id(event),
                session_id=str(getattr(event, "unified_msg_origin", "") or ""),
                text=text,
                speaker_id=str(event.get_self_id()),
                turn_id=AstrBotRuntimeAdapter.reply_turn_id(event, text),
                reply_to=AstrBotRuntimeAdapter.user_source_id(event),
                recall_ids=AstrBotRuntimeAdapter.recall_ids(event),
            )
            if reply is not None:
                AstrBotRuntimeAdapter.bind_reply(event, reply)
                self._begin_send_action(
                    event,
                    str(getattr(event, "unified_msg_origin", "") or ""),
                    self._bindings.run_tracer.run_id(event),
                    reply.turn_id,
                )
        except Exception:
            pass

    async def record_delivery(self, event) -> None:
        """Acknowledge only confirmed host delivery and delegate runtime writeback / 仅确认宿主已证实交付，并委托运行时写回。"""
        if self._may_observe(event):
            self._bindings.run_tracer.delivered(event)
        if not self._may_observe(event) or self._bindings.store is None:
            return
        assistant_source_id = AstrBotRuntimeAdapter.assistant_source_id(event)
        if not assistant_source_id:
            return
        if AstrBotRuntimeAdapter.episode_recorded(event):
            return
        self._bindings.services.runtime.record_delivery(
            run_id=self._bindings.run_tracer.run_id(event),
            session_id=str(getattr(event, "unified_msg_origin", "") or ""),
            decision=AstrBotRuntimeAdapter.runtime_action(event),
            reason=AstrBotRuntimeAdapter.runtime_reason(event),
            response_chars=AstrBotRuntimeAdapter.reply_chars(event),
            tool_calls=AstrBotRuntimeAdapter.tool_calls(event),
            user_source_id=AstrBotRuntimeAdapter.user_source_id(event),
            assistant_source_id=assistant_source_id,
            read_through_seq=AstrBotRuntimeAdapter.read_through_seq(event),
        )
        self._finish_send_action(event, ActionStatus.SUCCEEDED)
        AstrBotRuntimeAdapter.mark_episode_recorded(event)
        self._maybe_prune_runtime_episodes()

    async def observe_agent_begin(self, event, run_context) -> None:
        """Record bounded run-begin diagnostics for observable events / 为允许观察的事件记录有界运行开始诊断。"""
        if not self._may_observe(event):
            return
        self._bindings.run_tracer.begin(event)
        self._bindings.trace.record(
            "runtime",
            "agent_begin",
            {
                "decision": AstrBotRuntimeAdapter.runtime_action(event),
                "reason": AstrBotRuntimeAdapter.runtime_reason(event),
            },
        )

    async def observe_agent_done(self, event, run_context, response) -> None:
        """Record completion and delegate failed-agent outcomes without response bodies / 记录结束并委托失败智能体结果，不保存响应正文。"""
        if not self._may_observe(event):
            return
        role = str(getattr(response, "role", "") or "")
        self._bindings.run_tracer.done(event, "error" if role == "err" else "ok")
        self._bindings.trace.record("runtime", "agent_done", {"role": role})
        if role != "err":
            return
        self._finish_send_action(event, ActionStatus.FAILED, "agent_error")
        self._bindings.services.runtime.record_error(
            run_id=self._bindings.run_tracer.run_id(event),
            session_id=str(getattr(event, "unified_msg_origin", "") or ""),
            decision=AstrBotRuntimeAdapter.runtime_action(event),
            reason=AstrBotRuntimeAdapter.runtime_reason(event),
            error="agent_error",
            user_source_id=AstrBotRuntimeAdapter.user_source_id(event),
        )
        self._maybe_prune_runtime_episodes()

    def _tool_action_key(self, event, tool) -> str:
        """Build existing event/tool call correlation identity / 构造既有事件及工具调用关联身份。"""
        event_id = AstrBotRuntimeAdapter.event_id(event)
        tool_name = str(getattr(tool, "name", tool) or "tool")
        tool_id = str(
            getattr(tool, "id", "")
            or getattr(tool, "call_id", "")
            or ""
        )
        return f"{event_id}:{tool_name}:{tool_id}"

    def _begin_tool_action(self, event, tool, tool_args) -> None:
        """Record a tool attempt with name/correlation only, never argument values / 仅以名称及关联记录工具尝试，不保存参数值。"""
        executor = getattr(self._bindings, "action_executor", None)
        if executor is None:
            return
        try:
            attempts = getattr(self, "_action_attempts", None)
            if attempts is None:
                attempts = {}
                self._action_attempts = attempts
            key = self._tool_action_key(event, tool)
            record = executor.begin(
                ActionRequest(
                    session_id=str(getattr(event, "unified_msg_origin", "") or ""),
                    kind=ActionKind.TOOL_CALL,
                    text=str(getattr(tool, "name", tool) or ""),
                ),
                run_id=self._bindings.run_tracer.run_id(event),
                callback_key=key,
                at=self.clock(),
            )
            attempts[key] = record
        except Exception:  # noqa: BLE001 - Isolate audit failures / 隔离审计失败。
            pass

    def _finish_tool_action(self, event, tool, tool_result) -> None:
        """Record the matched tool terminal outcome, without tool result bodies / 记录匹配工具终态，不保存工具结果正文。"""
        executor = getattr(self._bindings, "action_executor", None)
        attempts = getattr(self, "_action_attempts", {})
        if executor is None:
            return
        try:
            key = self._tool_action_key(event, tool)
            record = attempts.pop(key, None)
            if record is None:
                return
            status = (
                ActionStatus.FAILED
                if tool_result_failed(tool_result)
                else ActionStatus.SUCCEEDED
            )
            executor.finish(record, status, at=self.clock())
        except Exception:  # noqa: BLE001
            pass

    async def observe_tool(self, event, tool, tool_args) -> None:
        """Observe tool policy metadata and audit its attempt; do not enforce after invocation / 观察工具规则元数据并审计尝试，不在调用后执行拦截。"""
        if not self._may_observe(event):
            return
        self._bindings.run_tracer.tool_begin(event, tool)
        self._begin_tool_action(event, tool, tool_args)
        call = AstrBotRuntimeAdapter.observe_tool(
            event, tool, tool_args, self._bindings.tool_policy
        )
        self._bindings.trace.record(
            "tool",
            "allowed" if call.allowed else "advisory_denied",
            {
                "tool": call.name,
                "argKeys": len(call.args_keys),
                "enforced": False,
            },
        )

    async def observe_tool_result(self, event, tool, tool_args, tool_result) -> None:
        """Observe completion and correlate audit without persisting result contents / 观察结束并关联审计，不持久保存结果正文。"""
        if not self._may_observe(event):
            return
        self._bindings.run_tracer.tool_end(event, tool)
        self._finish_tool_action(event, tool, tool_result)
        name = str(getattr(tool, "name", tool) or "")
        self._bindings.trace.record(
            "tool",
            "result",
            {"tool": name, "ok": bool(tool_result)},
        )

    async def start_jobs(self) -> None:
        """Start host resources, then one background task set after loaded callback / 启动宿主资源，并在加载回调后启动一组后台任务。"""
        await self._bindings.start()
        if (
            not self._bindings.ready
            or self._bindings.services is None
            or self._bindings.services.background_service.jobs.closed
            or self._bindings.services.background_service.tasks
        ):
            return
        self._bindings.services.background_service.start()


# Compatible registration paths / 兼容注册导入路径。
from .registration import _register, build_astrbot_hooks
