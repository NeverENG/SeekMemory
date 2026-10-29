"""Map one existing runtime attention decision to the host through finite typed bindings.

通过有限有类型依赖将一次既有运行时注意力决策映射到宿主。
"""

from __future__ import annotations

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ...app.runtime.contracts import RunDecision, WakeAction
from .events import to_runtime_input
from .runtime import AstrBotRuntimeAdapter
from .ports import HookHost


class AttentionHooks:
    """Apply one existing runtime decision through declared host dependencies / 通过声明的宿主依赖应用一次既有运行时决策。"""

    def __init__(self, host: HookHost | None = None) -> None:
        self.host = host
        self.clock = getattr(host, "clock", None) or (lambda: 0.0)

    @property
    def _bindings(self) -> HookHost:
        """Read only the declared host view; detached legacy tests bind fields locally.

        仅读取已声明宿主视图，独立的旧测试可在本地绑定字段；不转发任意属性。
        """
        return self.host if self.host is not None else self

    def _may_observe(self, event) -> bool:
        """Read existing observation permission; unavailable host state denies it / 读取既有观察权限，宿主状态不可用时拒绝。"""
        try:
            direct = getattr(self.host, "_may_observe", None)
            if callable(direct):
                return bool(direct(event))
            hooks = getattr(self.host, "hooks", None)
            if hooks is not None:
                return bool(hooks._may_observe(event))
        except Exception:  # noqa: BLE001 - Missing permission denies observation / 缺少权限时拒绝观察。
            return False
        return False

    def _address_names(self) -> tuple[str, ...]:
        """Read existing configured address names with the original fallback / 按原回退规则读取既有配置称呼。"""
        try:
            raw = str(self._bindings._c("attention_address_names", "大肥鱼,肥鱼") or "")
        except Exception:  # noqa: BLE001
            raw = "大肥鱼,肥鱼"
        return tuple(part.strip() for part in raw.split(",") if part.strip())

    def _owner_id(self) -> str:
        """Read the owner identity from the configured session / 从已配置会话读取所有者身份。"""
        try:
            umo = str(getattr(self._bindings, "owner_umo", "") or "")
            return umo.split(":")[-1] if umo else ""
        except Exception:  # noqa: BLE001
            return ""

    def _runtime_decision(self, event, mapped, now: float) -> RunDecision:
        """Reuse a cached decision or ask the runtime once and bind its result / 复用缓存决策，或只向运行时请求一次并绑定结果。"""
        cached = AstrBotRuntimeAdapter.get_extra(
            event, "_seekmemory_attention_decision", None
        )
        if isinstance(cached, RunDecision):
            return cached
        decision = self._bindings.services.runtime.observe(mapped, now=now)
        AstrBotRuntimeAdapter.set_extra(
            event, "_seekmemory_attention_decision", decision
        )
        return decision

    async def attention_gate(self, event: AstrMessageEvent) -> None:
        """Apply the existing runtime reply/stop decision before generation / 在生成前应用既有运行时回复或停止决策。"""
        if not self._bindings.ready or self._bindings.services is None or not self._may_observe(event):
            return
        if not bool(self._bindings._c("attention_policy_enabled", True)):
            return
        try:
            mapped = to_runtime_input(
                event,
                session_id=str(getattr(event, "unified_msg_origin", "") or ""),
                owner_id=self._owner_id(),
                names=self._address_names(),
                clock=self.clock,
            )
            if not mapped.text:
                return
            decision = self._runtime_decision(event, mapped, self.clock())
            self._bindings.journal.record(
                "attention",
                "reply" if decision.action is WakeAction.REPLY else "stop",
                decision.reason,
                context={"role": mapped.role},
            )
            if decision.action is not WakeAction.REPLY:
                event.stop_event()
        except Exception as exc:  # noqa: BLE001 - Policy failure allows host operation / 规则失败时允许宿主继续。
            logger.warning(f"[seekmemory] 开口策略失败（放行）：{type(exc).__name__}")
