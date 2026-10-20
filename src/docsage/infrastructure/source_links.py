"""Links a passage to its source: the web page it came from, or the file on disk."""

from __future__ import annotations

from pathlib import Path

from docsage.domain.models import Chunk, is_url


class FileAndUrlLocator:
    """Web pages link to their URL; files to a ``file://`` URI, opened at the page for PDFs.

    Sources are stored as they were indexed, so relative paths are resolved from ``base``
    (the working directory by default), where docsage was run.
    """

    def __init__(self, base: Path | None = None) -> None:
        self._base = base

    def href(self, chunk: Chunk) -> str | None:
        if is_url(chunk.source):
            return chunk.source
        path = Path(chunk.source)
        if not path.is_absolute():
            path = (self._base or Path.cwd()) / path
        try:
            uri = path.resolve().as_uri()
        except (OSError, ValueError):
            return None
        if chunk.first_page is not None:
            uri += f"#page={chunk.first_page}"
        return uri
