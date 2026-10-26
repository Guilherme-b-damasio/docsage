"""Finds a local Chrome, Chromium or Edge to drive headless, e.g. to print or capture a page.

Shared by the PDF export and ``scripts/screenshots.py``; nothing here touches the network.
"""

from __future__ import annotations

import shutil
from collections.abc import Sequence
from pathlib import Path

BROWSERS = (
    "google-chrome",
    "chromium",
    "chromium-browser",
    "chrome",
    "msedge",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
)
"""Executables on ``PATH`` first, then the usual install locations on Windows and macOS."""


def find_browser(candidates: Sequence[str] = BROWSERS) -> str | None:
    """The first candidate that is on ``PATH`` or exists as a file, else None."""
    for candidate in candidates:
        found = shutil.which(candidate) or (candidate if Path(candidate).is_file() else None)
        if found:
            return found
    return None


def themed(html: str, theme: str) -> str:
    """Pins the page to ``light`` or ``dark`` instead of following the system setting."""
    return html.replace("<html ", f'<html data-theme="{theme}" ', 1)
