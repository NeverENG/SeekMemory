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
    def __init__(self) -> None:
        super().__init__()
        self.document_language: str | None = None
        self.aria_labels: set[str] = set()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "html":
            self.document_language = attributes.get("lang")
        label = attributes.get("aria-label")
        if label:
            self.aria_labels.add(label)


def fail(message: str) -> int:
    print(f"FAIL: {message}")
    return 1


def main() -> int:
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
