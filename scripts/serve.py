#!/usr/bin/env python3
"""Start the authenticated loopback adapter (host_contract = 1).

    python scripts/serve.py --data-dir <dir> [--port 0] [--token <t>] [--config cfg.json]

Transport and composition live in adapters/loopback; this CLI retains the old command.
回环协议和服务组装位于 adapters/loopback；保留原启动命令。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from adapters.loopback.server import serve  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="SeekMemory loopback kernel")
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default="")
    parser.add_argument("--config", default="", help="JSON file with kernel config")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8")) if args.config else {}
    serve(Path(args.data_dir).expanduser().resolve(), port=args.port, token=args.token,
          config=config, quiet=args.quiet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
