"""AstrBot host binding for the runtime's default attention decision."""

from __future__ import annotations

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ...app.runtime.contracts import RunDecision, WakeAction
from .events import to_runtime_input
from .runtime import AstrBotRuntimeAdapter


class AttentionHooks:
    """Apply one runtime decision to the AstrBot event boundary."""

    def __init__(self, host=None) -> None:
        self.host = host
        self.clock = getattr(host, "clock", None) or (lambda: 0.0)

    def __getattr__(self, name):
        host = self.__dict__.get("host")
        if host is not None:
            return getattr(host, name)
        raise AttributeError(name)

    def _address_names(self) -> tuple[str, ...]:
        try:
            raw = str(self._c("attention_address_names", "大肥鱼,肥鱼") or "")
        except Exception:  # noqa: BLE001
            raw = "大肥鱼,肥鱼"
        return tuple(part.strip() for part in raw.split(",") if part.strip())

    def _owner_id(self) -> str:
        try:
            umo = str(getattr(self, "owner_umo", "") or "")
            return umo.split(":")[-1] if umo else ""
        except Exception:  # noqa: BLE001
            return ""

    def _runtime_decision(self, event, mapped, now: float) -> RunDecision:
        cached = AstrBotRuntimeAdapter.get_extra(
            event, "_seekmemory_attention_decision", None
        )
        if isinstance(cached, RunDecision):
            return cached
        decision = self.services.runtime.observe(mapped, now=now)
        AstrBotRuntimeAdapter.set_extra(
            event, "_seekmemory_attention_decision", decision
        )
        return decision

    async def attention_gate(self, event: AstrMessageEvent) -> None:
        """Apply the single runtime decision to AstrBot before generation."""
        if not self.ready or self.services is None or not self._may_observe(event):
            return
        if not bool(self._c("attention_policy_enabled", True)):
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
            self.journal.record(
                "attention",
                "reply" if decision.action is WakeAction.REPLY else "stop",
                decision.reason,
                context={"role": mapped.role},
            )
            if decision.action is not WakeAction.REPLY:
                event.stop_event()
        except Exception as exc:  # noqa: BLE001 - policy failure remains fail-open
            logger.warning(f"[seekmemory] 开口策略失败（放行）：{type(exc).__name__}")
