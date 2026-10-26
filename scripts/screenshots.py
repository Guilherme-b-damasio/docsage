"""Regenerates the README screenshots in ``docs/images`` from this repository's own docs.

    python scripts/screenshots.py [--browser PATH] [--out docs/images]

It indexes the Markdown files of the repository into a temporary index, renders the
HTML dashboard and an answer report with the regular renderers, and captures them with a
headless Chrome, Chromium or Edge. The answer text comes from ``DemoGenerator``, a canned
offline generator, so no API key is needed and the output is reproducible.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from docsage.container import Container, Settings
from docsage.domain.models import SearchResult
from docsage.infrastructure.headless_browser import find_browser, themed
from docsage.interfaces.paths import expand_paths

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("README.md", "ROADMAP.md", "CONTRIBUTING.md", "docs", "tests/fixtures/corpus")
QUESTION = "How does BM25 rank chunks?"


class DemoGenerator:
    """A fixed answer that cites the first two passages, standing in for Claude."""

    def generate(self, question: str, context: Sequence[SearchResult]) -> str:
        return (
            "docsage ranks passages with BM25: each query term adds a score that grows with "
            "how often the term appears in a chunk and how rare it is across the index [1]. "
            "The report charts how much every term contributed, so you can see why a "
            "passage ranked where it did [2]."
        )


def screenshot_command(
    browser: str, page: Path, png: Path, width: int, height: int
) -> list[str]:
    return [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--hide-scrollbars",
        f"--window-size={width},{height}",
        f"--screenshot={png}",
        page.resolve().as_uri(),
    ]


def render_pages(workdir: Path) -> dict[str, str]:
    """Indexes the repository docs into ``workdir`` and returns each page's HTML by name.

    Sources are indexed by their path relative to the repository root, so citations in
    the screenshots never show where the repository was checked out.
    """
    os.chdir(ROOT)
    container = Container(Settings(index_path=workdir / "index.json"), DemoGenerator())
    container.indexing_service().index(expand_paths([Path(source) for source in SOURCES]))
    report = container.answer_report_service("html").report(QUESTION, top_k=3)
    return {
        "dashboard-dark": themed(container.dashboard_service("html").render(top=12), "dark"),
        "answer-report-light": themed(report.content, "light"),
    }


SIZES = {"dashboard-dark": (1000, 1760), "answer-report-light": (1000, 1400)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--browser", help="Chrome, Chromium or Edge executable")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "images")
    args = parser.parse_args(argv)
    browser = args.browser or find_browser()
    if browser is None:
        print("No Chrome, Chromium or Edge found; pass --browser.", file=sys.stderr)
        return 1
    args.out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="docsage-shots-") as temp:
        workdir = Path(temp)
        for name, html in render_pages(workdir).items():
            page = workdir / f"{name}.html"
            page.write_text(html, encoding="utf-8")
            png = args.out / f"{name}.png"
            width, height = SIZES[name]
            command = screenshot_command(browser, page, png, width, height)
            subprocess.run(command, check=True, capture_output=True)
            print(f"Wrote {png}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
