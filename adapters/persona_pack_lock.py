"""Serialize cooperating persona-pack writers at the filesystem boundary.

在文件系统边界将协作的人格包写入者串行化。
"""
from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def pack_write_lock(directory: Path) -> Iterator[None]:
    """Lock a local authoring directory; reject symlink lock files / 锁定本地编辑目录，拒绝链接锁文件。"""
    if directory.is_symlink():
        raise ValueError("个人目录不允许符号链接")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / '.write.lock'
    if path.is_symlink():
        raise ValueError("编辑锁不允许符号链接")
    descriptor = os.open(path, os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        if os.name == "nt":
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)
