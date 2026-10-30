"""Own bounded diagnostic JSONL and locking; no message bodies, migrations or network calls.

管理有数量上限的诊断 JSONL 及锁，不处理消息正文、迁移或网络调用。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

try:
    from ..core.domain.operations.trace import FILTERS, clean_event, project_runs
except ImportError:  # Top-level package / 顶层包。
    from core.domain.operations.trace import FILTERS, clean_event, project_runs


from .ports import TraceClock


class TraceStore:
    """Own a bounded diagnostic snapshot and file lock; resources come from the caller / 管理有数量上限的诊断快照及文件锁，资源由调用方提供。"""
    def __init__(self, path: Path, *, retention_days: int = 7, max_rows: int = 5000,
                 clock: TraceClock = time.time) -> None:
        self.path = Path(path)
        self.retention_days = max(1, min(365, int(retention_days)))
        self.max_rows = max(1, min(5000, int(max_rows)))
        self.clock = clock
        self.started = clock()
        self.events: list[dict] = []
        self.persistence_error = False
        self._lock = threading.RLock()
        try:
            if self.path.exists():
                with self.path.open("rb") as stream:
                    while line := stream.readline(262145):
                        if len(line) > 262144:
                            while line and not line.endswith(b"\n"):
                                line = stream.readline(262145)
                            continue
                        try:
                            self.events.append(clean_event(json.loads(line)))
                            self.events = self.events[-self.max_rows:]
                        except (ValueError, TypeError, KeyError, AttributeError,
                                UnicodeDecodeError):
                            continue
                self.events = self._retained(self.events)
                self._persist(self.events)
        except OSError:
            self.persistence_error = True

    def _retained(self, rows: list[dict]) -> list[dict]:
        """Select rows inside the existing diagnostic retention limits / 选择既有诊断保留限制内的行。"""
        cutoff = self.clock() - self.retention_days * 86400
        return [r for r in rows if datetime.fromisoformat(r["at"]).timestamp() >= cutoff][-self.max_rows:]

    def _persist(self, rows: list[dict]) -> None:
        """Replace diagnostic JSONL atomically; preserve the old file on failed replacement / 原子替换诊断 JSONL，替换失败时保留旧文件。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=self.path.parent, prefix=".run-trace-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                for row in rows:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def append(self, row: dict) -> None:
        """Append a cleaned row; failures raise and preserve the saved snapshot / 追加已清理的行，失败抛错并保留已保存快照。"""
        with self._lock:
            try:
                row = clean_event(row)
                combined = [*self.events, row]
                rows = self._retained(combined)
                compact = len(rows) != len(combined)
                if len(combined) > self.max_rows:
                    # Evict up to 1% to avoid rewriting the full file on every hook.
                    # 每批淘汰至多 1%，避免每次钩子调用都重写整个文件。
                    rows = rows[-(self.max_rows - max(1, self.max_rows // 100) + 1):]
                if compact or self.persistence_error or not self.path.exists():
                    self._persist(rows)
                else:
                    # Repair failed appends from the last good snapshot on retry.
                    # 重试时从上次有效快照修复失败的追加。
                    with self.path.open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                self.events = rows
                self.persistence_error = False
            except (OSError, ValueError, TypeError, KeyError, AttributeError):
                self.persistence_error = True
                # The caller decides fail-open behavior; never acknowledge a failed write.
                # 由调用方决定如何隔离失败，不能将失败写入确认为成功。
                raise

    def snapshot(self, state: str = "all") -> dict:
        """Read projected runs; may compact expired diagnostics, with visible persistence status / 读取运行视图，允许裁剪过期诊断，并提供可见的持久化状态。"""
        if state not in FILTERS:
            raise ValueError("unknown_trace_filter")
        with self._lock:
            rows = self._retained(self.events)
            if len(rows) != len(self.events):
                try:
                    self._persist(rows)
                    self.events = rows
                    self.persistence_error = False
                except OSError:
                    self.persistence_error = True
            runs = project_runs(rows, self.started)
            if state != "all":
                runs = [r for r in runs if state in r["flags"]]
            visible = {r["id"] for r in runs}
            return {"runs": runs, "events": [r for r in rows if r["run_id"] in visible],
                    "capacity": self.max_rows, "retention_days": self.retention_days,
                    "persistence_error": self.persistence_error}
