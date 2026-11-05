"""Bound header and body receive time without touching memory-service execution."""

from __future__ import annotations

import socket
import time
from typing import BinaryIO


class IngressError(Exception):
    """Content-free HTTP rejection from the transport reader."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


class DeadlineReader:
    """Read from the handler's buffered stream, checking a whole-request deadline.

    ``readline`` is used by the standard HTTP request parser. Reading only bytes
    already in its buffer preserves any body bytes prefetched with the headers.
    """

    def __init__(self, connection: socket.socket, stream: BinaryIO,
                 header_seconds: float) -> None:
        self.connection = connection
        self.stream = stream
        self.deadline = time.monotonic() + header_seconds

    def _available(self) -> bytes:
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise IngressError(408, "request_timeout")
        self.connection.settimeout(remaining)
        try:
            chunk = self.stream.peek(1)
        except TimeoutError as exc:
            raise IngressError(408, "request_timeout") from exc
        if time.monotonic() >= self.deadline:
            raise IngressError(408, "request_timeout")
        return chunk

    def readline(self, limit: int = -1) -> bytes:
        parts: list[bytes] = []
        count = 0
        while limit < 0 or count < limit:
            available = self._available()
            if not available:
                break
            size = len(available) if limit < 0 else min(len(available), limit - count)
            newline = available.find(b"\n", 0, size)
            if newline >= 0:
                size = newline + 1
            parts.append(self.stream.read(size))
            count += size
            if newline >= 0:
                break
        return b"".join(parts)

    def read_exact(self, length: int, *, seconds: float) -> bytes:
        self.deadline = time.monotonic() + seconds
        parts: list[bytes] = []
        remaining = length
        while remaining:
            available = self._available()
            if not available:
                raise IngressError(400, "incomplete_body")
            part = self.stream.read(min(len(available), remaining))
            parts.append(part)
            remaining -= len(part)
        return b"".join(parts)

    def close(self) -> None:
        self.stream.close()
