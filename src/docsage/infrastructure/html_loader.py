"""Loads HTML files as Markdown-like text: tags stripped, headings kept as ``#`` lines.

Keeping the headings in Markdown form lets the Markdown chunker split HTML pages on
their sections and cite them as ``page.html, Setup > Install``. Only the standard
library is used, so HTML support needs no extra dependency.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path

from docsage.domain.models import Document

HEADINGS = {f"h{level}": level for level in range(1, 7)}

SKIPPED = frozenset({"script", "style", "noscript", "template", "svg", "iframe", "object"})
"""Elements whose content is never text a reader sees."""

BLOCKS = frozenset(
    {
        "address", "article", "aside", "blockquote", "br", "caption", "dd", "details",
        "dialog", "div", "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form",
        "header", "hr", "li", "main", "nav", "ol", "p", "section", "summary", "table",
        "tbody", "td", "tfoot", "th", "thead", "tr", "ul",
    }
)  # fmt: skip
"""Elements that start a new line of text."""

CELLS = frozenset({"td", "th"})

BOILERPLATE = frozenset({"nav", "header", "footer", "aside", "form", "dialog"})
"""Page chrome around a web page's main content: menus, banners, sidebars, forms."""

MAIN_SCOPES = ("main", "article")
"""Elements that hold a web page's main content, most specific last."""

_SPACES = re.compile(r"\s+")
_LOOKS_LIKE_HEADING = re.compile(r"^#{1,6}[ \t]")


class HtmlLoader:
    """Loads ``.html``/``.htm`` pages; the ``<title>`` goes into the metadata."""

    EXTENSIONS = frozenset({".html", ".htm", ".xhtml"})

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.EXTENSIONS

    def load(self, path: Path) -> Document:
        html = path.read_bytes().decode("utf-8", errors="replace")
        text, title = html_to_text(html)
        metadata = {"type": "html"}
        if title:
            metadata["title"] = title
        return Document(source=str(path), text=text, metadata=metadata)


def html_to_text(html: str) -> tuple[str, str]:
    """Returns the visible text of ``html`` as Markdown-like text, and the page title."""
    return _extract(html, _TextExtractor())


def main_content_to_text(html: str) -> tuple[str, str]:
    """Like ``html_to_text`` but keeps only a web page's main content.

    Text inside ``<main>`` (or, without one, inside ``<article>`` elements) is kept;
    navigation, headers, footers, sidebars and forms are dropped either way. A page
    with neither element keeps all of its non-boilerplate text.
    """
    scope = next((tag for tag in MAIN_SCOPES if _has_element(html, tag)), None)
    text, title = _extract(html, _TextExtractor(SKIPPED | BOILERPLATE, scope))
    if not text and scope is not None:
        # The main element held only boilerplate: fall back to the rest of the page.
        text, title = _extract(html, _TextExtractor(SKIPPED | BOILERPLATE))
    return text, title


def _extract(html: str, parser: _TextExtractor) -> tuple[str, str]:
    parser.feed(html)
    parser.close()
    return parser.text(), parser.title


def _has_element(html: str, tag: str) -> bool:
    finder = _ElementFinder(tag)
    finder.feed(html)
    finder.close()
    return finder.found


class _ElementFinder(HTMLParser):
    def __init__(self, tag: str) -> None:
        super().__init__(convert_charrefs=True)
        self._tag = tag
        self.found = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.found = self.found or tag == self._tag


class _TextExtractor(HTMLParser):
    def __init__(self, skipped: frozenset[str] = SKIPPED, scope: str | None = None) -> None:
        """Drops the content of ``skipped`` elements; with a ``scope`` tag, text outside
        every ``scope`` element is dropped as well (the page title is always read)."""
        super().__init__(convert_charrefs=True)
        self._skipped = skipped
        self._scope = scope
        self._scope_depth = 0
        self.title = ""
        self._blocks: list[str] = []
        self._line: list[str] = []
        self._skipping = 0
        self._heading = 0
        self._in_title = False
        self._in_pre = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == self._scope:
            self._flush()
            self._scope_depth += 1
        elif tag in self._skipped:
            self._skipping += 1
        elif tag == "title":
            self._in_title = True
        elif tag in HEADINGS:
            self._flush()
            self._heading = HEADINGS[tag]
        elif tag == "pre":
            self._flush()
            self._in_pre += 1
        elif tag in CELLS:
            self._line.append(" ")
        elif tag in BLOCKS:
            self._flush()

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in BLOCKS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag == self._scope:
            self._flush()
            self._scope_depth = max(0, self._scope_depth - 1)
        elif tag in self._skipped:
            self._skipping = max(0, self._skipping - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in HEADINGS and self._heading:
            title = _collapse("".join(self._line))
            self._line = []
            if title:
                self._blocks.append(f"{'#' * self._heading} {title}")
            self._heading = 0
        elif tag == "pre" and self._in_pre:
            self._in_pre -= 1
            code = "".join(self._line).strip("\n")
            self._line = []
            self._blocks.append(f"```\n{code}\n```")
        elif tag in BLOCKS and tag not in CELLS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._skipping:
            return
        if self._in_title:
            self.title = _collapse(self.title + " " + data)
        elif self._scope is None or self._scope_depth:
            self._line.append(data)

    def text(self) -> str:
        self._flush()
        return "\n\n".join(self._blocks)

    def _flush(self) -> None:
        if self._in_pre or self._heading:
            return
        line = _collapse("".join(self._line))
        self._line = []
        if line:
            # A paragraph such as "# 1 rule" must not turn into a heading.
            self._blocks.append("\\" + line if _LOOKS_LIKE_HEADING.match(line) else line)


def _collapse(text: str) -> str:
    return _SPACES.sub(" ", text).strip()
