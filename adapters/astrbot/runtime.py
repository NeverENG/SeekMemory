"""Map event fields and correlation extras without importing SDK event types.

映射事件字段及关联附加值，不导入 SDK 事件类型。
"""

from __future__ import annotations

from dataclasses import replace

from .time import utc8_timestamp
from .events import event_id as host_event_id, to_runtime_input

try:
    from ...app.runtime.contracts import (
        RunDecision,
        RuntimeInput,
        UserRunReceipt,
        WakeAction,
    )
    from ...app.runtime.recorder import RecordedReply
    from ...core.domain.memory.source import make_source_id
    from ...core.domain.social.interaction_policy import InteractionGate
    from ...app.runtime.tools import ToolPolicy, trace_tool_call
except ImportError:
    from app.runtime.contracts import (
        RunDecision,
        RuntimeInput,
        UserRunReceipt,
        WakeAction,
    )
    from app.runtime.recorder import RecordedReply
    from core.domain.memory.source import make_source_id
    from core.domain.social.interaction_policy import InteractionGate
    from app.runtime.tools import ToolPolicy, trace_tool_call


class AstrBotRuntimeAdapter:
    """Map event data and correlation extras without importing host event types / 映射事件数据及关联附加值，不导入宿主事件类型。"""

    @staticmethod
    def from_event(event, text: str, umo: str, sender: str,
                   unread_count: int = 0, unread_seq: int = 0,
                   received_at: float | None = None, owner_id: str = "",
                   names: tuple[str, ...] = (),
                   clock=None) -> RuntimeInput:
        """Use the single host-event mapper and supplied clock / 使用唯一宿主事件映射及给定时钟。"""
        mapped = to_runtime_input(
            event, session_id=umo, owner_id=owner_id, names=names,
            unread_count=unread_count, unread_seq=unread_seq, received_at=received_at,
            clock=clock,
        )
        value = str(text or "")
        return replace(
            mapped,
            session_id=str(umo or ""),
            text=value,
            speaker_id=str(sender or ""),
            mentioned=mapped.mentioned,
            question=("?" in value or "\uff1f" in value),
        )

    @staticmethod
    def source_event_time(source: dict | None) -> float:
        """Convert a known persisted Source instant; unknown legacy time returns zero / 转换已知持久原始消息时刻，未知旧时间返回零。"""
        raw = str((source or {}).get("at") or "")
        return utc8_timestamp(raw)

    @staticmethod
    def event_id(event) -> str:
        """Read one stable platform event identity for callback correlation / 读取用于回调关联的稳定平台事件身份。"""
        return host_event_id(event)

    @staticmethod
    def get_extra(event, key: str, default=None):
        """Read event correlation metadata with existing fallback / 按既有回退读取事件关联元数据。"""
        try:
            return event.get_extra(key, default)
        except Exception:
            return default

    @staticmethod
    def set_extra(event, key: str, value) -> None:
        """Write event correlation metadata at the host edge / 在宿主适配处写入事件关联元数据。"""
        try:
            event.set_extra(key, value)
        except Exception:  # noqa: BLE001 - Isolate host metadata failures / 隔离宿主元数据失败。
            return

    @classmethod
    def turn_id(cls, event) -> str:
        """Read or derive the existing stable user-turn identity / 读取或派生既有稳定用户轮次身份。"""
        return str(cls.get_extra(event, "_seekmemory_turn_id", "") or "")

    @classmethod
    def user_source_id(cls, event) -> str:
        """Read the bound immutable user Source identity / 读取已绑定不可变用户原始消息身份。"""
        return str(cls.get_extra(event, "_seekmemory_source_id", "") or "")

    @classmethod
    def reply_turn_id(cls, event, text: str) -> str:
        """Read the reply turn identity with its existing legacy fallback / 按既有旧回退读取回复轮次身份。"""
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
        """Read the bound immutable assistant Source identity / 读取已绑定不可变助手原始消息身份。"""
        return str(cls.get_extra(event, "_seekmemory_assistant_source_id", "") or "")

    @classmethod
    def reply_chars(cls, event) -> int:
        """Read observed assistant reply length / 读取观察到的助手回复长度。"""
        try:
            return int(cls.get_extra(event, "_seekmemory_reply_chars", 0) or 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def recall_ids(cls, event) -> tuple[str, ...]:
        """Read normalized final included memory IDs / 读取规范化的最终包含记忆编号。"""
        raw = cls.get_extra(event, "_seekmemory_recall_ids", ()) or ()
        return tuple(str(item) for item in raw)

    @classmethod
    def tool_calls(cls, event) -> tuple:
        """Read recorded tool names without arguments/results / 读取已记录工具名称，不包含参数或结果。"""
        return tuple(cls.get_extra(event, "_seekmemory_tool_calls", ()) or ())

    @classmethod
    def runtime_action(cls, event) -> str:
        """Read the existing bound runtime action / 读取既有绑定运行时动作。"""
        return str(
            cls.get_extra(event, "_seekmemory_runtime_action", "") or "observe"
        )

    @classmethod
    def runtime_reason(cls, event) -> str:
        """Read the existing bound runtime reason code / 读取既有绑定运行时原因码。"""
        return str(cls.get_extra(event, "_seekmemory_runtime_reason", "") or "")

    @classmethod
    def interaction_gate(cls, event) -> InteractionGate:
        """Read the bound generic interaction gate / 读取已绑定通用交互条件。"""
        value = cls.get_extra(event, "_seekmemory_interaction_gate", None)
        return value if isinstance(value, InteractionGate) else InteractionGate()

    @classmethod
    def bind_user(cls, event, receipt: UserRunReceipt) -> None:
        """Bind a saved user receipt and decision to this host event / 将已保存用户回执及决策绑定到宿主事件。"""
        cls.set_extra(event, "_seekmemory_turn_id", receipt.turn_id)
        cls.set_extra(event, "_seekmemory_source_id", receipt.source_id)
        cls.set_extra(event, "_seekmemory_read_through_seq", receipt.read_through_seq)

    @classmethod
    def read_through_seq(cls, event) -> int | None:
        """Read the covered-input cursor from the bound receipt / 从已绑定回执读取已覆盖输入游标。"""
        value = cls.get_extra(event, "_seekmemory_read_through_seq")
        return value if type(value) is int and value >= 0 else None

    @classmethod
    def bind_reply(cls, event, reply: RecordedReply) -> None:
        """Bind saved assistant evidence without claiming delivery / 绑定已保存助手证据，不声称已交付。"""
        cls.set_extra(event, "_seekmemory_turn_id", reply.turn_id)
        cls.set_extra(event, "_seekmemory_assistant_source_id", reply.assistant_source_id)
        cls.set_extra(event, "_seekmemory_reply_chars", reply.response_chars)
        cls.set_extra(event, "_seekmemory_recall_ids", ())

    @classmethod
    def set_recall_ids(cls, event, ids) -> None:
        """Bind only normalized final memory identities for later reinforcement / 仅绑定规范化最终记忆身份，供后续强化使用。"""
        cls.set_extra(
            event,
            "_seekmemory_recall_ids",
            tuple(str(item) for item in ids),
        )

    @classmethod
    def episode_recorded(cls, event) -> bool:
        """Read the existing per-event audit completion marker / 读取既有每事件审计完成标记。"""
        return bool(cls.get_extra(event, "_seekmemory_episode_recorded", False))

    @classmethod
    def mark_episode_recorded(cls, event) -> None:
        """Mark the event audit callback acknowledged / 标记事件审计回调已确认。"""
        cls.set_extra(event, "_seekmemory_episode_recorded", True)

    @classmethod
    def apply_decision(cls, event, decision: RunDecision) -> None:
        """Bind the existing runtime action/reason to host metadata / 将既有运行时动作及原因绑定到宿主元数据。"""
        cls.set_extra(event, "_seekmemory_runtime_action", decision.action.value)
        cls.set_extra(event, "_seekmemory_runtime_reason", decision.reason)

    @classmethod
    def bind_interaction(cls, event, gate: InteractionGate) -> None:
        """Bind a generic interaction gate without private snapshot content / 绑定通用交互条件，不包含私密快照内容。"""
        cls.set_extra(event, "_seekmemory_interaction_gate", gate)
        if gate.enforced and not gate.allow_reply:
            cls.set_extra(event, "_seekmemory_runtime_reason", gate.reason)

    @classmethod
    def apply_llm_gate(cls, event, decision: RunDecision, enabled: bool) -> None:
        """Map reply permission to AstrBot's prohibition flag only when enabled / 仅启用时将回复许可映射为 AstrBot 的禁止标记。"""
        if not enabled:
            return
        gate = cls.interaction_gate(event)
        if gate.enforced and not gate.allow_reply:
            try:
                event.should_call_llm(True)
            except Exception:  # noqa: BLE001 - Optional host gate / 可选宿主条件。
                pass
            return
        try:
            event.should_call_llm(
                not (decision.must_reply or decision.action is WakeAction.REPLY)
            )
        except Exception:  # noqa: BLE001 - Optional host gate / 可选宿主条件。
            return

    @classmethod
    def observe_tool(cls, event, tool, tool_args, policy: ToolPolicy):
        """Observe tool policy metadata and audit its attempt; do not enforce after invocation / 观察工具规则元数据并审计尝试，不在调用后执行拦截。"""
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
