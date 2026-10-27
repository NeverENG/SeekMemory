"""Run a test layer."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from layers import files_for  # noqa: E402



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", default="all", choices=("all", "unit", "contract", "conformance", "integration", "host", "smoke"))
    args = parser.parse_args()
    files = files_for(args.layer)
    if not files:
        print(f"no tests for layer {args.layer}")
        return 0
    for name in files:
        path = ROOT / "tests" / name
        print(f"== {path.relative_to(ROOT)}", flush=True)
        result = subprocess.run([sys.executable, str(path)], cwd=ROOT)
        if result.returncode:
            return result.returncode
    print(f"PASS layer={args.layer} files={len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
