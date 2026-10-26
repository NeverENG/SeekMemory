"""AstrBot event hooks.

The functions are undecorated so the plugin entrypoint can register them from
the real plugin module. AstrBot binds handlers by module path; using the hook
module path directly would leave them unbound after plugin reload.
"""

from __future__ import annotations

import datetime
import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter

from ..perceive.calls import log_call
from .astrbot_runtime import AstrBotRuntimeAdapter


class AstrBotHooks:
    """Host event mapping and delegation; owns no memory algorithms."""

    def _maybe_prune_runtime_episodes(self) -> None:
        """Keep runtime audit bounded without doing work on every message."""
        if self.store is None:
            return
        now = time.time()
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
        if self.services is None:
            return False
        return self.services.access_service.may_observe(
            str(getattr(event, "unified_msg_origin", "") or ""),
            str(event.get_sender_id()),
        )

    def _may_recall(self, event: AstrMessageEvent) -> bool:
        if self.services is None:
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
                event, text, umo, str(event.get_sender_id())
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
                # Match the old post-buffer-add observation: a non-deferred
                # turn is already present in the projection when observe runs.
                unread_count=len(self.buffer.items) + (0 if deferred else 1),
            )
            receipt = self.services.runtime.accept_user(
                runtime_input,
                event_id=AstrBotRuntimeAdapter.event_id(event),
                deferred=deferred,
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
            AstrBotRuntimeAdapter.apply_decision(event, receipt.decision)
            AstrBotRuntimeAdapter.apply_llm_gate(
                event,
                receipt.decision,
                bool(self._c("runtime_gate_enabled", False)),
            )
        except Exception:
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
                at=datetime.datetime.now().isoformat(timespec="seconds"),
                recall_ids=AstrBotRuntimeAdapter.recall_ids(event),
            )
            if reply is not None:
                AstrBotRuntimeAdapter.bind_reply(event, reply)
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
        )
        AstrBotRuntimeAdapter.mark_episode_recorded(event)
        self._maybe_prune_runtime_episodes()

    async def observe_agent_begin(self, event, run_context) -> None:
        if self._may_observe(event):
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
        role = str(getattr(response, "role", "") or "")
        if self._may_observe(event):
            self.run_tracer.done(event, "error" if role == "err" else "ok")
        self.trace.record("runtime", "agent_done", {"role": role})
        if role != "err":
            return
        self.services.runtime.record_error(
            run_id=self.run_tracer.run_id(event),
            session_id=str(getattr(event, "unified_msg_origin", "") or ""),
            decision=AstrBotRuntimeAdapter.runtime_action(event),
            reason=AstrBotRuntimeAdapter.runtime_reason(event),
            error="agent_error",
            user_source_id=AstrBotRuntimeAdapter.user_source_id(event),
        )
        self._maybe_prune_runtime_episodes()

    async def observe_tool(self, event, tool, tool_args) -> None:
        if self._may_observe(event):
            self.run_tracer.tool_begin(event, tool)
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
        if self._may_observe(event):
            self.run_tracer.tool_end(event, tool)
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


def _register(main_module: str, name: str, decorator):
    function = getattr(AstrBotHooks, name)
    function.__module__ = main_module
    function.__qualname__ = f"Main.{name}"
    return decorator(function)


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
    }
