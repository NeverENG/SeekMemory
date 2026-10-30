"""Load one production checkout and temporarily control only its offline clock.

加载一个生产代码版本，仅在离线评测期间控制时钟。
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import datetime
import importlib
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

from .memory_corpus import ANCHOR

PACKAGES = {"core", "app", "store", "recall", "perceive", "maintain", "services"}


@contextmanager
def target(repo: Path):
    """Reject mixed revisions; restore clock and search path after evaluation.

拒绝混用代码版本，评测后恢复时钟和导入查找路径。
    """
    repo = repo.resolve()
    sys.path.insert(0, str(repo))
    try:
        names = ("core.artifact", "core.source", "core.graph", "store", "store.cache",
                 "recall.pipeline", "recall.retriever", "recall.score", "recall.gate",
                 "recall.assemble", "recall.temporal", "recall.source_query")
        loaded = {name: importlib.import_module(name) for name in names}
        production = [module for name, module in list(sys.modules.items())
                      if name.split(".")[0] in PACKAGES and getattr(module, "__file__", None)]
        for module in production:
            if not Path(module.__file__).resolve().is_relative_to(repo):
                raise RuntimeError("mixed production checkouts; run one target per process")
        real_date, real_datetime = datetime.date, datetime.datetime

        class FixedDate(real_date):
            @classmethod
            def today(cls):
                return cls(ANCHOR.year, ANCHOR.month, ANCHOR.day)

        class FixedDatetime(real_datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(ANCHOR.year, ANCHOR.month, ANCHOR.day, 12, tzinfo=tz)

        with ExitStack() as stack:
            for module in production:
                for name, value in list(vars(module).items()):
                    if value is real_date:
                        stack.enter_context(patch.object(module, name, FixedDate))
                    elif value is real_datetime:
                        stack.enter_context(patch.object(module, name, FixedDatetime))
            stack.enter_context(patch.object(datetime, "date", FixedDate))
            stack.enter_context(patch.object(datetime, "datetime", FixedDatetime))
            yield SimpleNamespace(**{name.rsplit(".", 1)[-1]: module for name, module in loaded.items()})
    finally:
        sys.path.remove(str(repo))
