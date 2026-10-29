"""Safe audit classification and existing file/repository adapters; no SQL or model calls.

安全审计归类及既有文件、仓储转接，不包含 SQL 或模型调用。
"""

from __future__ import annotations

import json
import hashlib
import re
import threading
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from .tools import ToolCall
from .contracts.ports import EpisodeRepository


_SAFE_ERROR_CODE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,63}$")


@dataclass(frozen=True)
class EpisodeRecord:
    """Content-free runtime audit correlated with Source and run IDs / 通过原始消息及运行编号关联的不含正文审计。"""
    session_id: str
    at: str
    decision: str
    reason: str
    action: str
    delivered: bool
    response_chars: int = 0
    tool_calls: tuple[str, ...] = ()
    outcome: str = ""
    error: str = ""
    user_source_id: str = ""
    assistant_source_id: str = ""
    run_id: str = ""


@dataclass(frozen=True)
class EpisodeOutcome:
    """Safe delivery/tool outcome metadata / 安全的交付及工具结果信息。"""

    outcome: str
    error: str = ""
    delivered: bool = True
    tool_calls: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        """Whether the classified outcome is successful / 归类结果是否成功。"""
        return self.outcome == "ok"

    def fields(self) -> dict[str, Any]:
        """Return audit fields without message or tool payloads / 返回不含消息或工具正文的审计字段。"""

        return {
            "delivered": self.delivered,
            "tool_calls": self.tool_calls,
            "outcome": self.outcome,
            "error": self.error,
        }


def safe_error_code(error: Any) -> str:
    """Keep exception class names or bounded stable codes; discard exception bodies / 仅保留异常类型或有界稳定错误码，去掉异常正文。"""

    if error is None:
        return ""
    if isinstance(error, BaseException):
        code = type(error).__name__
    else:
        code = str(error or "").strip()
    return code if _SAFE_ERROR_CODE.fullmatch(code) else "error"


def normalize_tool_calls(tool_calls: Iterable[str | ToolCall] | None) -> tuple[str, ...]:
    """Retain tool names only, excluding arguments and results / 仅保留工具名，不保存参数和结果。"""

    if not tool_calls:
        return ()
    names: list[str] = []
    for item in tool_calls:
        if isinstance(item, ToolCall):
            value = item.name
        else:
            value = getattr(item, "name", item)
        name = str(value or "").strip()
        if name:
            names.append(name)
    return tuple(names)


def episode_outcome(
    *,
    delivered: bool,
    tool_calls: Iterable[str | ToolCall] | None = (),
    tool_failed: bool = False,
    error: Any = None,
) -> EpisodeOutcome:
    """Classify metadata; delivery failure precedes tool failure, then other errors / 按信息归类，交付失败优先，其次工具失败及其他错误。"""

    calls = normalize_tool_calls(tool_calls)
    code = safe_error_code(error)
    if not delivered:
        return EpisodeOutcome(
            outcome="delivery_failed",
            error=code or "delivery_failed",
            delivered=False,
            tool_calls=calls,
        )
    if tool_failed:
        return EpisodeOutcome(
            outcome="tool_error", error=code or "tool_error",
            delivered=True, tool_calls=calls,
        )
    if code:
        return EpisodeOutcome(
            outcome="error", error=code, delivered=True, tool_calls=calls
        )
    return EpisodeOutcome(outcome="ok", delivered=True, tool_calls=calls)


def delivery_failure_outcome(error: Any = None) -> EpisodeOutcome:
    """Build a safe known-delivery-failure outcome / 构造安全的已知交付失败结果。"""

    return EpisodeOutcome(
        outcome="delivery_failed",
        error=safe_error_code(error) or "delivery_failed",
        delivered=False,
    )


def delivery_failure_metadata(error: Any = None) -> dict[str, Any]:
    """Project safe delivery-failure audit fields / 投影安全的交付失败审计字段。"""

    return delivery_failure_outcome(error).fields()


class EpisodeSink(Protocol):
    """Persistence slot for one content-free runtime record / 一条不含正文运行记录的存储接口。"""
    def append(self, episode: EpisodeRecord) -> None:
        """Persist one record; raise on failure / 保存一条记录，失败抛异常。"""
        ...


class EpisodeRecorder:
    """Compatibility record-to-append adapter without independent rules / 兼容的记录到追加转接，不单独实现规则。"""
    def __init__(self, sink: EpisodeSink) -> None:
        self.sink = sink

    def record(self, episode: EpisodeRecord) -> None:
        """Forward audit to its sink; propagate failures for retry / 将审计交给存储，失败上抛以便重试。"""
        self.sink.append(episode)


class JsonlEpisodeStore:
    """Locked local JSONL audit; raise write failures and retain last_error / 加锁的本地 JSONL 审计，写入失败抛异常并保留 last_error。"""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self.last_error = ""

    def append(self, episode: EpisodeRecord) -> None:
        """Append safe metadata under the instance lock; do not swallow failed writes / 在实例锁内追加安全信息，不吞掉写入失败。"""
        with self._lock:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                payload = asdict(episode)
                payload["tool_calls"] = list(normalize_tool_calls(episode.tool_calls))
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False,
                                            sort_keys=True) + "\n")
                self.last_error = ""
            except Exception as exc:  # noqa: BLE001 - let the recorder retry / 交给记录器重试
                self.last_error = type(exc).__name__
                raise


class RepoEpisodeStore:
    """Adapt runtime audit to an injected repository without owning its lifecycle / 向注入仓储转交运行审计，不管理其生命周期。"""

    def __init__(self, repository: EpisodeRepository) -> None:
        self.repository = repository
        self.last_error = ""

    def append(self, episode: EpisodeRecord) -> None:
        """Use stable session/run identity for new rows; preserve old rows and report failures / 新行使用稳定会话及运行编号，保留旧行并报告失败。"""
        payload = asdict(episode)
        identity = hashlib.sha256(
            f"{episode.session_id}\0{episode.run_id}".encode("utf-8")
        ).hexdigest() if episode.run_id else uuid.uuid4().hex
        payload["id"] = f"ep_{identity}"
        payload["tool_calls"] = list(normalize_tool_calls(episode.tool_calls))
        try:
            self.repository.append(payload)
            self.last_error = ""
        except Exception as exc:  # noqa: BLE001 - let the recorder retry / 交给记录器重试
            self.last_error = type(exc).__name__
            raise
