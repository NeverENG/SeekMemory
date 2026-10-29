"""Contain ordinary diagnostic failures without suppressing business cancellation.

隔离普通诊断失败，不抑制业务取消；诊断资源由调用方管理。
"""
from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Any, TypeVar

T = TypeVar("T")


def diagnostic(action: Callable[..., T], *args: Any, **kwargs: Any) -> T | None:
    """Attempt diagnostics; ordinary failure never changes a business result.

    尝试诊断，普通失败不改变业务结果；取消等控制信号仍向上传递。
    """
    try:
        return action(*args, **kwargs)
    except Exception:
        return None


@contextmanager
def span(factory: Callable[..., AbstractContextManager[dict]],
         *args: Any, **kwargs: Any) -> Iterator[dict]:
    """Isolate diagnostic entry/exit failures; preserve exceptions from the body.

    隔离诊断进入和退出时的失败，保留业务体抛出的异常；不能由诊断吞掉业务失败。
    """
    manager = None
    try:
        manager = factory(*args, **kwargs)
        metrics = manager.__enter__()
    except Exception:
        manager, metrics = None, {}
    try:
        yield metrics
    except BaseException:
        if manager is not None:
            diagnostic(manager.__exit__, *sys.exc_info())
        raise
    else:
        if manager is not None:
            diagnostic(manager.__exit__, None, None, None)
