"""Prints HTML pages to PDF with a local headless Chrome, Chromium or Edge."""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from docsage.infrastructure.headless_browser import BROWSERS, find_browser, themed

PRINT_TIMEOUT_SECONDS = 120


class PdfExportError(RuntimeError):
    """No browser could be found, or it failed to print the page."""


def print_command(browser: str, page: Path, pdf: Path, profile: Path) -> list[str]:
    """Headless Chrome printing ``page`` to ``pdf`` without the date/URL header and footer;
    a throwaway ``profile`` keeps it apart from a browser the user already has open."""
    return [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-first-run",
        "--no-pdf-header-footer",
        f"--user-data-dir={profile}",
        f"--print-to-pdf={pdf}",
        page.resolve().as_uri(),
    ]


class HeadlessChromePdfPrinter:
    """Writes the page to a temporary file and lets a headless browser print it.

    The page is pinned to ``theme`` (light by default, as paper is) so the PDF does not
    depend on the system's dark mode. ``browser`` is an executable path; without one the
    ``candidates`` (the usual Chrome, Chromium and Edge locations) are searched when
    printing. ``run`` stands in for ``subprocess.run``, e.g. in tests.
    """

    def __init__(
        self,
        browser: str | None = None,
        theme: str = "light",
        run: Callable[..., Any] = subprocess.run,
        candidates: Sequence[str] = BROWSERS,
    ) -> None:
        self._browser = browser
        self._theme = theme
        self._run = run
        self._candidates = candidates

    def print_pdf(self, html: str) -> bytes:
        browser = self._browser or find_browser(self._candidates)
        if browser is None:
            raise PdfExportError("No Chrome, Chromium or Edge found; pass --browser")
        with tempfile.TemporaryDirectory(prefix="docsage-pdf-") as temp:
            workdir = Path(temp)
            page = workdir / "page.html"
            page.write_text(themed(html, self._theme), encoding="utf-8")
            pdf = workdir / "page.pdf"
            command = print_command(browser, page, pdf, workdir / "profile")
            try:
                completed = self._run(
                    command, capture_output=True, text=True, timeout=PRINT_TIMEOUT_SECONDS
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                raise PdfExportError(f"Could not run {browser}: {error}") from error
            if completed.returncode != 0 or not pdf.is_file():
                lines = (completed.stderr or "").strip().splitlines() or ["no output"]
                raise PdfExportError(f"{browser} could not print the page: {lines[-1]}")
            return pdf.read_bytes()
