"""State decoding and existing storage adapters; composition owns file paths and repository lifetime.

状态解析及既有存储转接，组装方管理文件路径和仓储生命周期。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import asdict
from pathlib import Path

from .contracts import SessionState
from .contracts.ports import StateRepository


def session_state_from_payload(
    session_id: str, raw: dict | None
) -> SessionState:
    """Decode known fields with legacy defaults; ignore unknown payload fields / 按旧数据默认值解析已知字段，忽略未知字段。"""
    key = str(session_id or "")
    if not isinstance(raw, dict):
        return SessionState(session_id=key)
    data = {
        name: raw[name]
        for name in SessionState.__dataclass_fields__
        if name in raw and raw[name] is not None
    }
    data["session_id"] = key
    try:
        return SessionState(**data)
    except TypeError:
        return SessionState(session_id=key)


class InMemoryStateStore:
    """Ephemeral state storage; get may return a live object / 临时状态存储，get 可能返回原对象。"""

    def __init__(self) -> None:
        self._items: dict[str, SessionState] = {}

    def get(self, session_id: str) -> SessionState:
        """Read or create state in this instance / 在当前实例读取或创建状态。"""
        key = str(session_id or "")
        state = self._items.get(key)
        if state is None:
            state = SessionState(session_id=key)
            self._items[key] = state
        return state

    def put(self, state: SessionState) -> None:
        """Replace one session in memory / 替换一个内存会话。"""
        self._items[str(state.session_id or "")] = state


class JsonStateStore:
    """Locked atomic JSON replacement; publish cached state only after success / 加锁原子替换 JSON，仅成功后发布内存状态。"""

    def __init__(self, path: str) -> None:
        self.path = Path(path)
        self._lock = threading.RLock()
        self._items: dict[str, dict] | None = None
        self.last_error = ""

    def _load(self) -> dict[str, dict]:
        if self._items is not None:
            return self._items
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._items = {}
            return self._items
        except Exception as exc:  # noqa: BLE001 - do not invent empty state / 不伪造空状态
            self.last_error = type(exc).__name__
            raise
        self._items = {}
        if isinstance(data, dict):
            self._items = {
                str(key): value for key, value in data.items()
                if isinstance(value, dict)
            }
        return self._items

    def get(self, session_id: str) -> SessionState:
        """Read decoded state; absence defaults, I/O and parse failures raise / 读取解析后的状态，不存在用默认值，读写及解析失败抛异常。"""
        key = str(session_id or "")
        with self._lock:
            return session_state_from_payload(key, self._load().get(key))

    def put(self, state: SessionState) -> None:
        """Save a candidate snapshot; replacement failure preserves old memory and disk / 保存候选快照，替换失败保留内存及磁盘旧状态。"""
        key = str(state.session_id or "")
        with self._lock:
            items = dict(self._load())
            items[key] = asdict(state)
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                payload = json.dumps(items, ensure_ascii=False, sort_keys=True)
                fd, temp = tempfile.mkstemp(prefix=".runtime-state-", dir=str(self.path.parent))
                try:
                    with os.fdopen(fd, "w", encoding="utf-8") as handle:
                        handle.write(payload)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temp, self.path)
                    self._items = items
                    self.last_error = ""
                finally:
                    if os.path.exists(temp):
                        os.unlink(temp)
            except Exception as exc:  # noqa: BLE001 - let orchestration retry / 交给编排重试
                self.last_error = type(exc).__name__
                raise


class RepoStateStore:
    """Adapt session state to an injected repository; failures are observable / 向注入仓储转交会话状态，失败可被识别。"""

    def __init__(self, repository: StateRepository) -> None:
        self.repository = repository
        self.last_error = ""

    def get(self, session_id: str) -> SessionState:
        """Decode the persisted state; repository failures raise instead of inventing empty state / 解析持久状态，仓储失败抛异常，不伪造空状态。"""
        key = str(session_id or "")
        try:
            raw = self.repository.get(key)
        except Exception as exc:  # noqa: BLE001 - preserve unknown state / 保留未知状态
            self.last_error = type(exc).__name__
            raise
        self.last_error = ""
        return session_state_from_payload(key, raw)

    def put(self, state: SessionState) -> None:
        """Save state or retain last_error and raise / 保存状态，失败保留 last_error 并抛异常。"""
        try:
            self.repository.put(str(state.session_id or ""), asdict(state))
            self.last_error = ""
        except Exception as exc:  # noqa: BLE001 - let orchestration retry / 交给编排重试
            self.last_error = type(exc).__name__
            raise
