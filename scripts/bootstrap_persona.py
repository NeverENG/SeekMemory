"""把可信的人格文件写入唯一的人格链（一次性 bootstrap）。

用法（在插件根目录或容器内执行）：

    python scripts/bootstrap_persona.py --db <memory.db> --file <persona.json>

它只做管理侧的一次写入：不创建 Source、不触发抽取、不写第二份人格存储。
人格内容由 `docs/PERSONA_SEED.md` 定义的 persona 文件提供；写入后由召回
常驻层每轮注入，Dream 之后在同一人格链上做增量修订。

退出码：
    0  写入成功（或 --dry-run 校验通过）
    1  文件无效或写入失败
    2  参数错误
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
    """读取人格文件并写入当前人格链，返回进程退出码。"""
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
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
