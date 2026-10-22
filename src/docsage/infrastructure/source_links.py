"""Links a passage to its source: the web page it came from, or the file on disk."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from docsage.domain.models import Chunk, SearchResult, is_url
from docsage.domain.ports import PassageLocator, SourceLocator

TEXT_FRAGMENT_SOURCES = (".html", ".htm", ".md", ".markdown", ".txt", ".rst")
"""File types a browser can open at a passage; web pages always can."""

RANGE_WORDS = 6
"""Words quoted at each end of the passage to mark the range to scroll to."""

MAX_TERM_DIRECTIVES = 4
"""How many matched terms are highlighted on top of the passage itself."""


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


class ServedSourceLocator:
    """Web pages link to their URL; files to ``endpoint?path=<source>``, where a web server
    serves indexed files (browsers do not open ``file://`` links from an ``http`` page)."""

    def __init__(self, endpoint: str) -> None:
        self._endpoint = endpoint

    def href(self, chunk: Chunk) -> str | None:
        if is_url(chunk.source):
            return chunk.source
        href = f"{self._endpoint}?path={quote(chunk.source, safe='')}"
        if chunk.first_page is not None:
            href += f"#page={chunk.first_page}"
        return href


class HighlightingLocator:
    """Decorates a locator so a text source opens at the passage, with its terms marked.

    ``passage_href`` appends a `text fragment
    <https://wicg.github.io/scroll-to-text-fragment/>`_ (``#:~:text=``) that points at
    the passage's first and last words and at the terms it matched: browsers that
    support fragments (Chrome, Edge, Safari) scroll there and highlight them, the others
    ignore the fragment and open the source as before. Formats a browser cannot point
    into (PDFs, Word documents) and links that already carry a fragment, such as a PDF
    page, are left exactly as the wrapped locator returned them.
    """

    def __init__(self, inner: SourceLocator) -> None:
        self._inner = inner

    def href(self, chunk: Chunk) -> str | None:
        return self._inner.href(chunk)

    def passage_href(self, result: SearchResult) -> str | None:
        href = self._inner.href(result.chunk)
        if href is None or "#" in href or not _points_into(result.chunk.source):
            return href
        directives = text_directives(result)
        return f"{href}#:~:{'&'.join(directives)}" if directives else href


def passage_href(locator: SourceLocator, result: SearchResult) -> str | None:
    """The link a report opens for ``result``: inside the passage where the locator can."""
    if isinstance(locator, PassageLocator):
        return locator.passage_href(result)
    return locator.href(result.chunk)


def text_directives(result: SearchResult) -> list[str]:
    """``text=`` directives for the passage's range first, then its matched terms.

    The range comes first so a browser scrolls to the passage rather than to the first
    place one of its words happens to appear.
    """
    directives = [directive for directive in [_range_directive(result.chunk.text)] if directive]
    terms = _matched_texts(result)[:MAX_TERM_DIRECTIVES]
    directives.extend(f"text={_encoded(term)}" for term in terms)
    return directives


def _range_directive(text: str) -> str:
    """``text=start,end``, or the whole passage when it is short enough to quote."""
    words = text.split()
    if not words:
        return ""
    if len(words) <= 2 * RANGE_WORDS:
        return f"text={_encoded(' '.join(words))}"
    start = _encoded(" ".join(words[:RANGE_WORDS]))
    end = _encoded(" ".join(words[-RANGE_WORDS:]))
    return f"text={start},{end}"


def _matched_texts(result: SearchResult) -> list[str]:
    """The passage's matched words as they are written, each one once, in text order."""
    text = result.chunk.text
    found = (text[item.start : item.end] for item in result.highlights)
    return list(dict.fromkeys(word for word in found if word.strip()))


def _encoded(text: str) -> str:
    """Percent-encodes one directive part; ``-`` and ``,`` separate the parts."""
    return quote(text, safe="").replace("-", "%2D")


def _points_into(source: str) -> bool:
    return is_url(source) or source.lower().endswith(TEXT_FRAGMENT_SOURCES)
