"""Read built English HTML and validate language/accessibility controls; never build or modify pages.

读取已构建英文 HTML 并校验语言及无障碍控件，不构建或修改页面。
"""
from __future__ import annotations

import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGLISH_SITE = ROOT / "site" / "en"
EXPECTED_CONTROLS = {
    "Switch to dark mode",
    "Switch to light mode",
    "Use system color scheme",
}


class PageContractParser(HTMLParser):
    """Collect page language and accessible control labels.

    收集页面语言及无障碍控件标签。
    """
    def __init__(self) -> None:
        super().__init__()
        self.document_language: str | None = None
        self.aria_labels: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Read language and labels from HTML start tags.

        从 HTML 起始标签读取语言及标签。
        """
        attributes = dict(attrs)
        if tag == "html":
            self.document_language = attributes.get("lang")
        label = attributes.get("aria-label")
        if label:
            self.aria_labels.add(label)


def fail(message: str) -> int:
    """Print one failure and return a nonzero command status.

    输出一项失败并返回非零命令状态。
    """
    print(f"FAIL: {message}")
    return 1


def main() -> int:
    """Check every built English page and the home-page palette controls.

    检查全部已构建英文页面及首页主题控件。
    """
    pages = sorted(ENGLISH_SITE.rglob("*.html"))
    if not pages:
        return fail(f"no English pages found under {ENGLISH_SITE.relative_to(ROOT)}")

    for page in pages:
        parser = PageContractParser()
        parser.feed(page.read_text(encoding="utf-8"))
        if parser.document_language != "en":
            return fail(f"{page.relative_to(ROOT)} has html lang={parser.document_language!r}, expected 'en'")

    home = ENGLISH_SITE / "index.html"
    parser = PageContractParser()
    parser.feed(home.read_text(encoding="utf-8"))
    missing = EXPECTED_CONTROLS - parser.aria_labels
    if missing:
        return fail(f"{home.relative_to(ROOT)} is missing accessible controls: {sorted(missing)}")

    print(f"PASS: {len(pages)} English pages use lang=en and expose English palette controls")
    return 0


if __name__ == "__main__":
    sys.exit(main())
