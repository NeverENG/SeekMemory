"""Run from a source checkout: python3 scripts/console_http.py --data-dir <dir>."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import ModuleType

# A stable package namespace supports relative imports without importing main.py.
# The source checkout's folder name is not part of the public command.
package = ModuleType("_seekmemory_standalone")
package.__path__ = [str(Path(__file__).resolve().parents[1])]
sys.modules[package.__name__] = package
main = importlib.import_module(f"{package.__name__}.adapters.console.server").main

if __name__ == "__main__":
    raise SystemExit(main())
