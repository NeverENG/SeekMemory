"""Run each file with isolated unittest discovery, including late definitions.

逐文件在独立进程中执行 unittest 发现，包括入口之后的测试定义。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from layers import files_for  # noqa: E402



def main() -> int:
    """Discover every file in the layer and return failure if any file fails.

发现本层每个文件，只要有文件失败就返回失败。
"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--layer", default="all", choices=("all", "unit", "contract", "conformance", "integration", "host", "smoke"))
    args = parser.parse_args()
    files = files_for(args.layer)
    if not files:
        print(f"no tests for layer {args.layer}")
        return 0
    failures = []
    for name in files:
        path = ROOT / "tests" / name
        print(f"== {path.relative_to(ROOT)}", flush=True)
        # Import without running __main__; isolate SDK fakes between files.
        # 导入时不运行 __main__，并在文件间隔离 SDK 替身。
        result = subprocess.run([
            sys.executable, "-X", "utf8", "-B", "-m", "unittest", "discover",
            "-s", str(ROOT / "tests"), "-p", name, "-q",
        ], cwd=ROOT)
        if result.returncode:
            failures.append(name)
    if failures:
        print(f"FAIL layer={args.layer} files={len(files)} failed={','.join(failures)}")
        return 1
    print(f"PASS layer={args.layer} files={len(files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
