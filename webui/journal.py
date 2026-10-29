"""包含源码位置和任务关联信息的有界业务事件。"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections import deque
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from types import FrameType
from uuid import uuid4

Scalar = str | int | float | bool | None
_ROOT = Path(__file__).resolve().parents[1]
_MAX_FILE_BYTES = 1024 * 1024
_REQUIRED_FIELDS = ("id", "at", "kind", "status", "message", "taskId")


def _location(frame: FrameType, line: int) -> dict:
    """描述调用帧，不采集局部变量或安装目录的绝对路径。

    Args:
        frame: 调用者或异常的栈帧。
        line: 事件或异常发生的行号。

    Returns:
        模块、相对文件名、函数和从 1 开始的行号。
    """
    path = Path(frame.f_code.co_filename).resolve()
    return {
        "module": str(frame.f_globals.get("__name__", "unknown")),
        "file": path.relative_to(_ROOT).as_posix()
        if path.is_relative_to(_ROOT)
        else path.name,
        "function": frame.f_code.co_name,
        "line": line,
    }


class Journal:
    """持久化有界事件，提供可复用的业务阶段日志封装。"""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.events: deque[dict] = deque(maxlen=500)
        self.task_id: ContextVar[str] = ContextVar("seekmemory_task_id", default="")
        self.persistence_error = False
        try:
            for file in (path.with_suffix(".jsonl.1"), path):
                if not file.exists():
                    continue
                # 每个文件只读末尾 1 MiB，截断的首行会按损坏行跳过。
                offset = max(0, file.stat().st_size - _MAX_FILE_BYTES)
                with file.open("rb") as stream:
                    stream.seek(offset)
                    lines = stream.read().splitlines()
                for line in lines:
                    try:
                        row = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue
                    if not isinstance(row, dict):
                        continue
                    if not all(
                        isinstance(row.get(key), str) for key in _REQUIRED_FIELDS
                    ):
                        continue
                    # 兼容旧事件，其源码位置保持未知。
                    self.events.append(row)
        except OSError:
            self.persistence_error = True
        unfinished: dict[str, dict] = {}
        for event in self.events:
            if not event["taskId"] or event.get("stage"):
                continue
            if event["status"] not in {
                "queued",
                "running",
                "succeeded",
                "failed",
                "cancelled",
                "interrupted",
            }:
                continue
            unfinished[event["taskId"]] = event
        for task_id, event in unfinished.items():
            if event["status"] in {"queued", "running"}:
                self.record(
                    event["kind"], "interrupted", "上次进程已停止，任务中断", task_id
                )

    def record(
        self,
        kind: str,
        status: str,
        message: str,
        task_id: str = "",
        *,
        stage: str = "",
        context: Mapping[str, Scalar] | None = None,
        duration_ms: float | None = None,
        error: BaseException | None = None,
        source: dict | None = None,
    ) -> None:
        """追加结构化事件，不暴露异常正文或局部变量。

        Args:
            kind: 业务操作类型。
            status: 生命周期状态或日志级别。
            message: 固定的操作摘要，不传入对话内容。
            task_id: 显式关联 ID，未指定时从当前任务继承。
            stage: 稳定的业务阶段名称，与生命周期状态分开记录。
            context: 显式标量 ID 和计数，不传入正文或凭证。
            duration_ms: 可选的阶段耗时。
            error: 异常对象，仅记录其类型与栈帧位置。
            source: 阶段封装采集的调用位置，未指定时使用直接调用者。
        """
        frame = inspect.currentframe()
        try:
            if source is None and frame is not None:
                caller = frame.f_back
                # Transparent diagnostic wrappers preserve the business location.
                # 透明的诊断包装保留业务代码位置。
                while caller and caller.f_locals.get("__tracebackhide__") is True:
                    caller = caller.f_back
                if caller is not None:
                    source = _location(caller, caller.f_lineno)
        finally:
            del frame
        failure = None
        if error is not None:
            frames = []
            tb = error.__traceback__
            while tb is not None:
                frames.append(_location(tb.tb_frame, tb.tb_lineno))
                tb = tb.tb_next
            failure = {"type": type(error).__name__, "frames": frames[-12:]}
        level = "INFO"
        if status == "failed":
            level = "ERROR"
        elif status in {"warning", "cancelled", "interrupted"}:
            level = "WARNING"
        elif status == "debug":
            level = "DEBUG"

        safe_context = {}
        for key, value in list((context or {}).items())[:32]:
            if value is not None and type(value) not in (str, int, float, bool):
                continue
            safe_context[str(key)[:80]] = (
                value[:200] if isinstance(value, str) else value
            )
        row = {
            "id": uuid4().hex,
            "at": datetime.now(timezone.utc).isoformat(),
            "kind": kind,
            "status": status,
            "message": message[:1000],
            "taskId": task_id or self.task_id.get(),
            "level": level,
            "stage": stage,
            "source": source,
            "context": safe_context,
            "durationMs": duration_ms,
            "error": failure,
        }
        self.events.append(row)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > _MAX_FILE_BYTES:
                self.path.replace(self.path.with_suffix(".jsonl.1"))
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
            self.persistence_error = False
        except OSError:
            self.persistence_error = True

    def trim(self, target: int = 400) -> int:
        """Drop the oldest Trace rows while preserving the newest bounded sample."""
        target = max(0, min(int(target), self.events.maxlen or 500))
        removed = max(0, len(self.events) - target)
        for _ in range(removed):
            self.events.popleft()
        if not removed:
            return 0
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            with temporary.open("w", encoding="utf-8") as stream:
                for event in self.events:
                    stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            temporary.replace(self.path)
            self.path.with_suffix(".jsonl.1").unlink(missing_ok=True)
            self.persistence_error = False
        except OSError:
            self.persistence_error = True
        return removed

    @contextmanager
    def span(
        self, kind: str, stage: str, **context: Scalar
    ) -> Iterator[dict[str, Scalar]]:
        """跟踪同步或异步业务阶段，原样传播失败。

        Args:
            kind: 业务操作类型。
            stage: 日志视图中显示的稳定阶段名称。
            **context: 显式的安全计数和 ID；返回的上下文可补充结果。

        Yields:
            可变的标量上下文，用于记录阶段结果计数。

        Raises:
            BaseException: 原始操作异常或取消异常，原样抛出。
        """
        frame = inspect.currentframe()
        try:
            caller = frame.f_back if frame else None
            # contextlib 会进入此生成器；调用位置应指向业务代码的 with 语句。
            while caller and (
                caller.f_globals.get("__name__") == "contextlib"
                or caller.f_locals.get("__tracebackhide__") is True
            ):
                caller = caller.f_back
            source = _location(caller, caller.f_lineno) if caller else None
        finally:
            del frame
            del caller
        self.record(
            kind,
            "running",
            "阶段已开始",
            stage=stage,
            context=context,
            source=source,
        )
        start = perf_counter()
        try:
            yield context
        except BaseException as exc:
            self.record(
                kind,
                "cancelled" if isinstance(exc, asyncio.CancelledError) else "failed",
                "阶段中断",
                stage=stage,
                context=context,
                duration_ms=round((perf_counter() - start) * 1000, 2),
                error=exc,
                source=source,
            )
            raise
        else:
            self.record(
                kind,
                "succeeded",
                "阶段已完成",
                stage=stage,
                context=context,
                duration_ms=round((perf_counter() - start) * 1000, 2),
                source=source,
            )
