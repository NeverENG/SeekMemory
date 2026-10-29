"""Read navigation and mirrored Markdown links without modifying documents.

读取导航及镜像 Markdown 链接，不修改文档。
"""
from __future__ import annotations
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

try:
    import yaml
except ImportError:
    print("FAIL: install requirements-docs.txt")
    raise SystemExit(2)

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
CONFIG = ROOT / "mkdocs.yml"
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

def fail(message: str) -> None:
    """Print a failure and stop with nonzero status.

    输出失败并以非零状态停止。
    """
    print(f"FAIL: {message}")
    raise SystemExit(1)

def nav_paths(value):
    """Yield document paths from the existing nested navigation format.

    从既有嵌套导航格式产生文档路径。
    """
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, list):
        for item in value:
            yield from nav_paths(item)
        return
    if isinstance(value, dict):
        for item in value.values():
            if isinstance(item, str) and item.endswith(".md"):
                yield item
            else:
                yield from nav_paths(item)

def check_links(files: list[Path]) -> None:
    """Reject missing local Markdown targets while leaving external links untouched.

    拒绝缺少的本地 Markdown 目标，保留外部链接。
    """
    for path in files:
        text = path.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            raw = match.group(1).strip().strip("<>")
            target = raw.split("#", 1)[0].split("?", 1)[0].strip()
            if not target:
                continue
            parsed = urlparse(target)
            if parsed.scheme or target.startswith(("#", "/")):
                continue
            candidate = (path.parent / target).resolve()
            if target.endswith(".md") and not candidate.is_file():
                fail(f"broken link in {path.relative_to(ROOT)}: {raw}")

def main() -> int:
    """Validate navigation, mirrored page sets and relative Markdown links.

    校验导航、镜像页面集合及相对 Markdown 链接。
    """
    if not CONFIG.is_file():
        fail("mkdocs.yml is missing")
    if not DOCS.is_dir():
        fail("docs/ is missing")
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    nav = config.get("nav")
    if not nav:
        fail("mkdocs.yml has no nav")
    nav_files = list(nav_paths(nav))
    if len(nav_files) != len(set(nav_files)):
        fail("nav contains duplicate page entries")
    for name in nav_files:
        path = DOCS / name
        if not path.is_file() or path.suffix != ".md":
            fail(f"nav references invalid page: {name}")
    all_md = sorted(p.relative_to(DOCS).as_posix() for p in DOCS.rglob("*.md"))
    if set(nav_files) != set(all_md):
        fail(f"nav mismatch: docs={sorted(set(all_md)-set(nav_files))} nav={sorted(set(nav_files)-set(all_md))}")
    extra = [p.name for p in DOCS.glob("*.md") if p.name != "index.md"]
    if extra:
        fail(f"top-level docs are not allowed: {extra}")
    zh = {p.relative_to(DOCS/"zh").as_posix() for p in (DOCS/"zh").rglob("*.md")}
    en = {p.relative_to(DOCS/"en").as_posix() for p in (DOCS/"en").rglob("*.md")}
    if zh != en:
        fail(f"zh/en mismatch: {sorted(zh-en)} / {sorted(en-zh)}")
    check_links([DOCS / name for name in all_md])
    print(f"PASS: {len(all_md)} pages, {len(nav_files)} nav entries")
    return 0

if __name__ == "__main__":
    sys.exit(main())
