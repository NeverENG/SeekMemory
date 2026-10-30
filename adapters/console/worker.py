"""Keep console runtime creation, management calls and cleanup on one thread."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import TracebackType

from ...webui.console_api import ApiResponse, ConsoleApi
from .runtime import ConsoleRuntime


class ConsoleWorker:
    """Serialize application operations independently of HTTP connection I/O."""

    def __init__(self, data_dir: Path) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="console-store")
        try:
            self._runtime = self._executor.submit(ConsoleRuntime, data_dir).result()
            self._api = ConsoleApi(self._runtime.management, status=self._runtime.status,
                                   traces=self._runtime.traces.snapshot)
        except BaseException:
            self._executor.shutdown()
            raise

    def handle(self, action: str, method: str, query: dict[str, str],
               body: object = None) -> ApiResponse:
        """Dispatch parsed input to the thread that owns SQLite and the cache."""
        return self._executor.submit(self._api.handle, action, method, query, body).result()

    def __enter__(self) -> ConsoleWorker:
        return self

    def __exit__(self, _type: type[BaseException] | None, _error: BaseException | None,
                 _traceback: TracebackType | None) -> None:
        try:
            self._executor.submit(self._runtime.close).result()
        finally:
            self._executor.shutdown()
