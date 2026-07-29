#!/usr/bin/env python3
"""Render docs/handbook/*.html to the committed PDFs.

Chromium comes from the QA suite's Playwright dependency. `channel="chromium"`
uses the full browser build rather than the headless shell, which the repo does
not install.
"""

from __future__ import annotations

import pathlib
import sys

HANDBOOK = pathlib.Path(__file__).resolve().parent.parent / "docs" / "handbook"
PAGES = [
    ("review.html", "01-lab-review.pdf", "SDLC Lab — Review"),
    ("system-map.html", "02-system-map.pdf", "SDLC Lab — How the machine works"),
    ("round-3-preflight.html", "03-round-3-preflight.pdf", "Round 3 pre-flight"),
]
FOOTER = (
    '<div style="width:100%;font:9px sans-serif;color:#999;padding:0 12mm;'
    'display:flex;justify-content:space-between"><span>{title}</span>'
    '<span class="pageNumber"></span></div>'
)


def main() -> int:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as play:
        browser = play.chromium.launch(channel="chromium")
        for src, dst, title in PAGES:
            page = browser.new_page()
            # Print the light theme regardless of the renderer's OS setting.
            page.emulate_media(media="screen", color_scheme="light")
            page.goto((HANDBOOK / src).as_uri())
            page.wait_for_timeout(500)
            page.pdf(
                path=str(HANDBOOK / dst),
                format="A4",
                print_background=True,
                margin={"top": "13mm", "bottom": "15mm", "left": "12mm", "right": "12mm"},
                display_header_footer=True,
                header_template="<div></div>",
                footer_template=FOOTER.format(title=title),
            )
            page.close()
            print(f"{dst}: {(HANDBOOK / dst).stat().st_size // 1024} KB")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
