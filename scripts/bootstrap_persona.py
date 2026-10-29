"""Read authored persona JSON and initialize the single persona chain; dry-run validates without storage. Own and close the opened Store; never create Sources. Exit 0 on success, 1 on invalid input/write failure and 2 on invalid arguments.

读取人工人格 JSON 并初始化唯一人格链，试运行只校验不访问存储。拥有并关闭打开的 Store，不创建 Source。成功退出 0，输入或写入失败退出 1，参数错误退出 2。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.management_service import ManagementService  # noqa: E402
from store import Store  # noqa: E402
from store.cache import Cache  # noqa: E402


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="bootstrap the single persona chain from a persona file"
    )
    parser.add_argument("--db", required=True, help="memory.db 路径")
    parser.add_argument("--file", required=True, help="persona 文件路径（JSON）")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验文件，不写库",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Read persona input, optionally commit through ManagementService and always close owned storage.

    读取人格输入，可通过 ManagementService 提交，并始终关闭自有存储。
    """
    args = _parser().parse_args(argv)
    seed_path = Path(args.file)
    if not seed_path.is_file():
        print(f"persona 文件不存在：{seed_path}", file=sys.stderr)
        return 1
    try:
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"persona 文件读取失败：{exc}", file=sys.stderr)
        return 1

    if args.dry_run:
        from core.persona import persona_payload_from_file

        try:
            payload = persona_payload_from_file(seed)
        except ValueError as exc:
            print(f"persona 文件无效：{exc}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "valid": True,
                    "seedId": payload["seed_id"],
                    "seedVersion": payload["seed_version"],
                    "corpusCount": payload["corpus_count"],
                    "textChars": len(payload["text"]),
                },
                ensure_ascii=False,
            )
        )
        return 0

    store = Store(args.db)
    try:
        cache = Cache(store.artifacts)
        cache.load()
        service = ManagementService(
            store.artifacts, store.sources, store.ledger, cache, None
        )
        result = service.bootstrap_persona(seed)
    except (OSError, ValueError) as exc:
        print(f"写入人格失败：{exc}", file=sys.stderr)
        return 1
    finally:
        store.close()
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
