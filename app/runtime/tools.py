"""One tool policy and its existing host filter; request filtering enforces, observation only reports.

唯一工具策略及既有宿主过滤，请求过滤执行拦截，观察仅报告。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class ToolCall:
    """Metadata for an observed call, excluding argument values / 观察到的调用信息，不含参数值。"""

    name: str
    allowed: bool
    args_keys: tuple[str, ...] = ()
    enforced: bool = False

    @property
    def advisory(self) -> bool:
        """Whether observation did not enforce a request-path filter / 是否仅观察而未执行请求过滤。"""
        return not self.enforced


@dataclass(frozen=True)
class ToolGuardDecision:
    """Pre-request tool eligibility decision / 模型请求前的工具资格判断。"""

    tool_name: str
    allowed: bool
    enforced: bool = True
    reason: str = ""


class ToolPolicy:
    """One allowlist for pure decisions and the existing host-shaped filter / 纯判断及既有宿主过滤共用的一份允许列表。"""

    def __init__(self, allowed_prefixes: tuple[str, ...] = ()) -> None:
        self.allowed_prefixes = tuple(str(x) for x in allowed_prefixes if x)

    def allows(self, name: str) -> bool:
        """Check a tool name against configured prefixes / 按已配置前缀判断工具名。"""
        value = str(name or "")
        if not self.allowed_prefixes:
            return True
        return any(value.startswith(prefix) for prefix in self.allowed_prefixes)

    def check_tool(self, tool_name: str,
                   tool_args: Mapping[str, Any] | None = None) -> ToolGuardDecision:
        """Return eligibility without executing or mutating the host / 返回资格，不执行或修改宿主。"""
        allowed = self.allows(tool_name)
        return ToolGuardDecision(
            tool_name=str(tool_name or ""),
            allowed=allowed,
            enforced=True,
            reason="allowed" if allowed else "policy_denied",
        )

    def filter_tool_set(self, tool_set: Any) -> tuple[str, ...]:
        """Remove denied tools before the model request; host-shape failures are isolated. Observational hooks cannot enforce this filter.

        模型请求前移除禁止工具，隔离宿主对象异常；观察钩子不能执行此过滤。
        """
        removed: list[str] = []
        remove_tool = getattr(tool_set, "remove_tool", None)
        if not callable(remove_tool):
            return ()
        tools = list(getattr(tool_set, "tools", ()) or ())
        for tool in tools:
            name = str(getattr(tool, "name", "") or "")
            if not name or self.allows(name):
                continue
            try:
                remove_tool(name)
                removed.append(name)
            except Exception:  # noqa: BLE001 - filter failure is isolated / 隔离过滤失败
                continue
        return tuple(removed)

    def trace_call(self, tool_name: str, tool_args) -> ToolCall:
        """Classify an observed call using names and argument keys only / 仅按工具名及参数键归类观察到的调用。"""
        name = str(tool_name or "")
        args = tool_args if isinstance(tool_args, dict) else {}
        return ToolCall(
            name=name,
            allowed=self.allows(name),
            args_keys=tuple(sorted(str(key) for key in args)),
            enforced=False,
        )


def tool_result_failed(tool_result: Any) -> bool:
    """Inspect only failure metadata; never persist result content / 仅检查失败信息，不保存结果正文。"""
    if tool_result is None:
        return False
    for attr in ("isError", "is_error"):
        try:
            if bool(getattr(tool_result, attr, False)):
                return True
        except Exception:  # noqa: BLE001 - metadata probe is isolated / 隔离信息探测失败
            pass
    try:
        status = str(getattr(tool_result, "status", "") or "").lower()
    except Exception:  # noqa: BLE001 - metadata probe is isolated / 隔离信息探测失败
        status = ""
    return status in {"error", "failed", "failure", "cancelled", "canceled"}


def trace_tool_call(tool_name: str, tool_args, policy: ToolPolicy) -> ToolCall:
    """Compatibility helper delegating to the single tool policy / 委托唯一工具策略的兼容函数。"""
    return policy.trace_call(tool_name, tool_args)
