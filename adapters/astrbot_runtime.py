"""AstrBot event mapping for the host-agnostic AgentRuntime."""

from __future__ import annotations

import time

try:
    from ..app.runtime.contracts import (
        RunDecision,
        RuntimeInput,
        UserRunReceipt,
        WakeAction,
    )
    from ..app.runtime.recorder import RecordedReply
    from ..core.source import make_source_id
    from ..app.runtime.tools import ToolPolicy, trace_tool_call
except ImportError:
    from app.runtime.contracts import (
        RunDecision,
        RuntimeInput,
        UserRunReceipt,
        WakeAction,
    )
    from app.runtime.recorder import RecordedReply
    from core.source import make_source_id
    from app.runtime.tools import ToolPolicy, trace_tool_call


class AstrBotRuntimeAdapter:
    """Translate AstrBot message events without importing AstrBot types."""

    @staticmethod
    def from_event(event, text: str, umo: str, sender: str,
                   unread_count: int = 0, unread_seq: int = 0) -> RuntimeInput:
        try:
            private = bool(event.is_private_chat())
        except Exception:  # noqa: BLE001 - unknown host event defaults to group
            private = False
        value = str(text or "")
        try:
            created_at = float(getattr(event, "created_at", 0.0) or 0.0)
        except (TypeError, ValueError):
            created_at = 0.0
        direct = bool(getattr(event, "is_at_or_wake_command", False))
        return RuntimeInput(
            session_id=str(umo or ""),
            text=value,
            speaker_id=str(sender or ""),
            private=private,
            mentioned=private or direct,
            question=("?" in value or "\uff1f" in value),
            unread_count=max(0, int(unread_count)),
            unread_seq=max(0, int(unread_seq)),
            event_time=created_at,
            received_at=time.time(),
        )

    @staticmethod
    def event_id(event) -> str:
        try:
            return str(
                getattr(getattr(event, "message_obj", None), "message_id", "") or ""
            )
        except Exception:
            return ""

    @staticmethod
    def get_extra(event, key: str, default=None):
        try:
            return event.get_extra(key, default)
        except Exception:
            return default

    @staticmethod
    def set_extra(event, key: str, value) -> None:
        try:
            event.set_extra(key, value)
        except Exception:  # noqa: BLE001 - host metadata must not break a run
            return

    @classmethod
    def turn_id(cls, event) -> str:
        return str(cls.get_extra(event, "_seekmemory_turn_id", "") or "")

    @classmethod
    def user_source_id(cls, event) -> str:
        return str(cls.get_extra(event, "_seekmemory_source_id", "") or "")

    @classmethod
    def reply_turn_id(cls, event, text: str) -> str:
        """Return the host turn id, preserving the legacy fallback identity."""
        existing = cls.turn_id(event)
        if existing:
            return existing
        try:
            return make_source_id(
                session_id=str(getattr(event, "unified_msg_origin", "") or ""),
                speaker_id=str(event.get_sender_id()),
                role="assistant",
                text=str(text or ""),
            )
        except Exception:
            return ""

    @classmethod
    def assistant_source_id(cls, event) -> str:
        return str(cls.get_extra(event, "_seekmemory_assistant_source_id", "") or "")

    @classmethod
    def reply_chars(cls, event) -> int:
        try:
            return int(cls.get_extra(event, "_seekmemory_reply_chars", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def recall_ids(cls, event) -> tuple[str, ...]:
        raw = cls.get_extra(event, "_seekmemory_recall_ids", ()) or ()
        return tuple(str(item) for item in raw)

    @classmethod
    def tool_calls(cls, event) -> tuple:
        return tuple(cls.get_extra(event, "_seekmemory_tool_calls", ()) or ())

    @classmethod
    def runtime_action(cls, event) -> str:
        return str(
            cls.get_extra(event, "_seekmemory_runtime_action", "") or "observe"
        )

    @classmethod
    def runtime_reason(cls, event) -> str:
        return str(cls.get_extra(event, "_seekmemory_runtime_reason", "") or "")

    @classmethod
    def bind_user(cls, event, receipt: UserRunReceipt) -> None:
        cls.set_extra(event, "_seekmemory_turn_id", receipt.turn_id)
        cls.set_extra(event, "_seekmemory_source_id", receipt.source_id)

    @classmethod
    def bind_reply(cls, event, reply: RecordedReply) -> None:
        cls.set_extra(event, "_seekmemory_turn_id", reply.turn_id)
        cls.set_extra(event, "_seekmemory_assistant_source_id", reply.assistant_source_id)
        cls.set_extra(event, "_seekmemory_reply_chars", reply.response_chars)
        cls.set_extra(event, "_seekmemory_recall_ids", ())

    @classmethod
    def set_recall_ids(cls, event, ids) -> None:
        cls.set_extra(
            event,
            "_seekmemory_recall_ids",
            tuple(str(item) for item in ids),
        )

    @classmethod
    def episode_recorded(cls, event) -> bool:
        return bool(cls.get_extra(event, "_seekmemory_episode_recorded", False))

    @classmethod
    def mark_episode_recorded(cls, event) -> None:
        cls.set_extra(event, "_seekmemory_episode_recorded", True)

    @classmethod
    def apply_decision(cls, event, decision: RunDecision) -> None:
        cls.set_extra(event, "_seekmemory_runtime_action", decision.action.value)
        cls.set_extra(event, "_seekmemory_runtime_reason", decision.reason)

    @staticmethod
    def apply_llm_gate(event, decision: RunDecision, enabled: bool) -> None:
        if not enabled:
            return
        try:
            event.should_call_llm(
                decision.must_reply or decision.action is WakeAction.REPLY
            )
        except Exception:  # noqa: BLE001 - host version may not expose the gate
            return

    @classmethod
    def observe_tool(cls, event, tool, tool_args, policy: ToolPolicy):
        name = str(getattr(tool, "name", tool) or "")
        call = trace_tool_call(name, tool_args, policy)
        existing = cls.tool_calls(event)
        cls.set_extra(event, "_seekmemory_tool_calls", existing + (call.name,))
        if not call.allowed:
            mismatches = cls.get_extra(
                event, "_seekmemory_tool_policy_mismatches", ()
            ) or ()
            cls.set_extra(
                event,
                "_seekmemory_tool_policy_mismatches",
                tuple(mismatches) + (call.name,),
            )
        cls.set_extra(event, "_seekmemory_tool_policy_enforced", False)
        return call
