"""AstrBot event hooks.

The functions are undecorated so the plugin entrypoint can register them from
the real plugin module. AstrBot binds handlers by module path; using the hook
module path directly would leave them unbound after plugin reload.
"""

from __future__ import annotations

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter

from ...app.runtime.contracts import ActionKind, ActionRequest, ActionStatus
from ...app.runtime.tools import tool_result_failed
from ...perceive.calls import log_call
from .attention import AttentionHooks
from .runtime import AstrBotRuntimeAdapter


class AstrBotHooks:
    """Host event mapping and delegation; owns no memory algorithms."""

    def __init__(self, host=None) -> None:
        self.host = host
        self.clock = getattr(host, "clock", None) or (lambda: 0.0)

    def __getattr__(self, name):
        host = self.__dict__.get("host")
        if host is not None:
            return getattr(host, name)
        raise AttributeError(name)

    def _maybe_prune_runtime_episodes(self) -> None:
        """Keep runtime audit bounded without doing work on every message."""
        if self.store is None:
            return
        now = self.clock()
        if now - self._last_runtime_prune_at < 60:
            return
        try:
            self.store.runtime_episodes.prune(
                retention_days=int(self._c("runtime_episode_retention_days", 30)),
                max_rows=int(self._c("runtime_episode_max_rows", 5000)),
            )
            self._last_runtime_prune_at = now
        except Exception:
            pass

    def _may_observe(self, event: AstrMessageEvent) -> bool:
        if not self.ready or self.services is None:
            return False
        return self.services.access_service.may_observe(
            str(getattr(event, "unified_msg_origin", "") or ""),
            str(event.get_sender_id()),
        )

    def _may_recall(self, event: AstrMessageEvent) -> bool:
        if not self.ready or self.services is None:
            return False
        return self.services.access_service.may_recall(
            str(getattr(event, "unified_msg_origin", "") or ""),
            str(event.get_sender_id()),
        )

    async def inject_memory(self, event: AstrMessageEvent, req) -> None:
        trace_allowed = False
        trace_info = None
        trace_status = "unknown"
        try:
            if not self._may_recall(event):
                return
            trace_allowed = True
            if not self.ready or self.cache is None:
                return
            text = (event.message_str or "").strip()
            if not text:
                return

            umo = str(getattr(event, "unified_msg_origin", "") or "")
            policy = getattr(self, "tool_policy", None)
            removed_tools = ()
            if bool(self._c("runtime_tool_filter_enabled", False)) and policy is not None:
                removed_tools = policy.filter_tool_set(
                    getattr(req, "func_tool", None)
                )
            if removed_tools:
                self.trace.record(
                    "tool", "guard_removed",
                    {"count": len(removed_tools), "enforced": True},
                )
                self.journal.record(
                    "tool", "info", "runtime tool guard removed tools",
                    context={"removed": len(removed_tools), "enforced": True},
                )
            runtime_input = AstrBotRuntimeAdapter.from_event(
                event, text, umo, str(event.get_sender_id()),
                owner_id=getattr(self, "_owner_id", lambda: "")(),
                names=getattr(self, "_address_names", lambda: ())(),
                clock=self.clock,
            )
            context = self.services.runtime.build_context(runtime_input)
            block, info = context.text, context.info
            self.services.capacity_service.set_context_chars(len(block))
            log_call(self._calls_path(), umo, info)
            AstrBotRuntimeAdapter.set_recall_ids(
                event, info.get("final_ids", ())
            )
            self.journal.record(
                "recall",
                "info",
                "召回文本已组装",
                stage="assemble",
                context={key: info[key] for key in ("mode", "picked", "chars")},
            )
            relationship_policy = getattr(self, "relationship_policy", None)
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
                # 给记忆块加个明确的框：模型才知道这些是"自己记得的事"，
                # 而不是散落在系统提示里的匿名文本。
                framed = (
                    "\n\n【你的记忆】\n"
                    "下面是你自己记得的事，来自你的记忆库。自然带出来，别逐条复述，"
                    "也别说「根据记忆」。没有这一段，就说明你此刻没想起来。\n"
                    + block
                    + "\n"
                )
                req.system_prompt = (req.system_prompt or "") + framed
                self.services.runtime.record_context_injection(context)
                if self._c("debug_log", False):
                    logger.info(f"[seekmemory] 注入 {len(block)} 字")
            trace_info, trace_status = info, "ok"
        except Exception as e:  # noqa: BLE001
            trace_status = "error"
            self.journal.record("recall", "failed", "召回失败", error=e)
            logger.error(f"[seekmemory] 注入失败（不影响回复）：{type(e).__name__}")
        finally:
            if trace_allowed:
                self.run_tracer.request(event, trace_info, trace_status)

    async def buffer_message(self, event: AstrMessageEvent) -> None:
        try:
            if not self._may_observe(event):
                return
            text = (event.message_str or "").strip()
            if not text or self.buffer is None:
                return
            umo = str(getattr(event, "unified_msg_origin", "") or "")
            sender = str(event.get_sender_id())
            deferred = self._admit_deferred()
            runtime_input = AstrBotRuntimeAdapter.from_event(
                event,
                text,
                umo,
                sender,
                owner_id=getattr(self, "_owner_id", lambda: "")(),
                names=getattr(self, "_address_names", lambda: ())(),
                clock=self.clock,
            )
            decision = AstrBotRuntimeAdapter.get_extra(
                event, "_seekmemory_attention_decision", None
            )
            receipt = self.services.runtime.accept_user(
                runtime_input,
                event_id=AstrBotRuntimeAdapter.event_id(event),
                deferred=deferred,
                decision=decision,
            )
            AstrBotRuntimeAdapter.set_extra(
                event, "_seekmemory_attention_decision", receipt.decision
            )
            if self.buffer.save_error:
                self.journal.record(
                    "capacity",
                    "warning",
                    "pending save failed",
                    context={"error": self.buffer.save_error},
                )
            try:
                self._self_id = str(event.get_self_id())
            except Exception:
                pass
            AstrBotRuntimeAdapter.bind_user(event, receipt)
            self._schedule_proactive(umo)
            AstrBotRuntimeAdapter.apply_decision(event, receipt.decision)
            relationship_policy = getattr(self, "relationship_policy", None)
            if relationship_policy is not None:
                gate = relationship_policy.decide(
                    runtime_input,
                    receipt.decision,
                    source_id=receipt.source_id,
                )
                AstrBotRuntimeAdapter.bind_interaction(event, gate)
                self.trace.record(
                    "relationship",
                    "enforced" if gate.enforced else "observed",
                    {
                        "would_allow_reply": gate.allow_reply,
                        "would_style": gate.style.value,
                        "policy_version": relationship_policy.version,
                    },
                )
                if gate.enforced and not gate.allow_reply:
                    self.services.runtime.clear_wait(umo)
            AstrBotRuntimeAdapter.apply_llm_gate(
                event,
                receipt.decision,
                bool(self._c("runtime_gate_enabled", False)),
            )
        except Exception:
            pass

    def _schedule_proactive(self, session_id: str) -> None:
        if not bool(self._c("proactive_enabled", False)):
            return
        try:
            delay = float(self._c("proactive_idle_seconds", 1800))
            schedule = getattr(self.services.runtime, "schedule_proactive", None)
            if callable(schedule):
                schedule(session_id, delay, now=self.clock())
        except Exception:  # noqa: BLE001 - proactive scheduling is fail-open
            pass

    def _begin_send_action(self, event, session_id: str, run_id: str, turn_id: str) -> None:
        executor = getattr(self, "action_executor", None)
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
        except Exception:  # noqa: BLE001 - audit must not break replies
            pass

    def _finish_send_action(self, event, status: ActionStatus, reason: str = "") -> None:
        executor = getattr(self, "action_executor", None)
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
        try:
            if self._may_observe(event):
                self.run_tracer.response(
                    event,
                    "error" if getattr(response, "role", "") == "err" else "ok",
                )
            if not self._may_observe(event) or self.store is None:
                return
            if str(getattr(response, "role", "assistant")) == "err":
                return
            text = str(getattr(response, "completion_text", "") or "").strip()
            if not text:
                return
            reply = self.services.runtime.record_reply(
                run_id=self.run_tracer.run_id(event),
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
                    self.run_tracer.run_id(event),
                    reply.turn_id,
                )
        except Exception:
            pass

    async def record_delivery(self, event) -> None:
        if self._may_observe(event):
            self.run_tracer.delivered(event)
        if not self._may_observe(event) or self.store is None:
            return
        assistant_source_id = AstrBotRuntimeAdapter.assistant_source_id(event)
        if not assistant_source_id:
            return
        if AstrBotRuntimeAdapter.episode_recorded(event):
            return
        self.services.runtime.record_delivery(
            run_id=self.run_tracer.run_id(event),
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
        if not self._may_observe(event):
            return
        self.run_tracer.begin(event)
        self.trace.record(
            "runtime",
            "agent_begin",
            {
                "decision": AstrBotRuntimeAdapter.runtime_action(event),
                "reason": AstrBotRuntimeAdapter.runtime_reason(event),
            },
        )

    async def observe_agent_done(self, event, run_context, response) -> None:
        if not self._may_observe(event):
            return
        role = str(getattr(response, "role", "") or "")
        self.run_tracer.done(event, "error" if role == "err" else "ok")
        self.trace.record("runtime", "agent_done", {"role": role})
        if role != "err":
            return
        self._finish_send_action(event, ActionStatus.FAILED, "agent_error")
        self.services.runtime.record_error(
            run_id=self.run_tracer.run_id(event),
            session_id=str(getattr(event, "unified_msg_origin", "") or ""),
            decision=AstrBotRuntimeAdapter.runtime_action(event),
            reason=AstrBotRuntimeAdapter.runtime_reason(event),
            error="agent_error",
            user_source_id=AstrBotRuntimeAdapter.user_source_id(event),
        )
        self._maybe_prune_runtime_episodes()

    def _tool_action_key(self, event, tool) -> str:
        event_id = AstrBotRuntimeAdapter.event_id(event)
        tool_name = str(getattr(tool, "name", tool) or "tool")
        tool_id = str(
            getattr(tool, "id", "")
            or getattr(tool, "call_id", "")
            or ""
        )
        return f"{event_id}:{tool_name}:{tool_id}"

    def _begin_tool_action(self, event, tool, tool_args) -> None:
        executor = getattr(self, "action_executor", None)
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
                run_id=self.run_tracer.run_id(event),
                callback_key=key,
                at=self.clock(),
            )
            attempts[key] = record
        except Exception:  # noqa: BLE001 - audit failure must not break the run
            pass

    def _finish_tool_action(self, event, tool, tool_result) -> None:
        executor = getattr(self, "action_executor", None)
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
        if not self._may_observe(event):
            return
        self.run_tracer.tool_begin(event, tool)
        self._begin_tool_action(event, tool, tool_args)
        call = AstrBotRuntimeAdapter.observe_tool(
            event, tool, tool_args, self.tool_policy
        )
        self.trace.record(
            "tool",
            "allowed" if call.allowed else "advisory_denied",
            {
                "tool": call.name,
                "argKeys": len(call.args_keys),
                "enforced": False,
            },
        )

    async def observe_tool_result(self, event, tool, tool_args, tool_result) -> None:
        if not self._may_observe(event):
            return
        self.run_tracer.tool_end(event, tool)
        self._finish_tool_action(event, tool, tool_result)
        name = str(getattr(tool, "name", tool) or "")
        self.trace.record(
            "tool",
            "result",
            {"tool": name, "ok": bool(tool_result)},
        )

    async def start_jobs(self) -> None:
        await self.start()
        if (
            not self.ready
            or self.services is None
            or self.services.background_service.jobs.closed
            or self.services.background_service.tasks
        ):
            return
        self.services.background_service.start()


def _register(main_module: str, name: str, decorator, component: str = "hooks"):
    async def handler(self, *args, **kwargs):
        return await getattr(getattr(self, component), name)(*args, **kwargs)

    handler.__module__ = main_module
    handler.__qualname__ = f"Main.{name}"
    # AstrBot 用 module + __name__ 生成 handler 唯一名；闭包同名会被当成同一个 handler
    # 并互相覆盖。这里必须让每个 hook 拥有独立名字。
    handler.__name__ = name
    return decorator(handler)


def build_astrbot_hooks(main_module: str) -> dict:
    """Return handlers registered against the real plugin module path."""
    return {
        "inject_memory": _register(
            main_module, "inject_memory", filter.on_llm_request()
        ),
        "buffer_message": _register(
            main_module,
            "buffer_message",
            filter.event_message_type(filter.EventMessageType.ALL),
        ),
        "capture_reply": _register(
            main_module, "capture_reply", filter.on_llm_response()
        ),
        "record_delivery": _register(
            main_module, "record_delivery", filter.after_message_sent()
        ),
        "observe_agent_begin": _register(
            main_module, "observe_agent_begin", filter.on_agent_begin()
        ),
        "observe_agent_done": _register(
            main_module, "observe_agent_done", filter.on_agent_done()
        ),
        "observe_tool": _register(
            main_module, "observe_tool", filter.on_using_llm_tool()
        ),
        "observe_tool_result": _register(
            main_module, "observe_tool_result", filter.on_llm_tool_respond()
        ),
        "start_jobs": _register(
            main_module, "start_jobs", filter.on_astrbot_loaded()
        ),
        "attention_gate": _register(
            main_module,
            "attention_gate",
            filter.event_message_type(filter.EventMessageType.ALL, priority=9999),
            component="attention",
        ),
    }
