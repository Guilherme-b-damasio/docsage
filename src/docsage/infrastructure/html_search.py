"""Renders search results as a self-contained HTML page, optionally with a search form."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape
from urllib.parse import urlencode

from docsage.domain.models import SearchResult, SourceFilter
from docsage.domain.ports import SourceLocator
from docsage.infrastructure.html_page import page
from docsage.infrastructure.html_report import REPORT_CSS, source_html
from docsage.infrastructure.source_links import (
    FileAndUrlLocator,
    HighlightingLocator,
    passage_href,
)
from docsage.infrastructure.svg_charts import CHART_CSS

SEARCH_CSS = """
nav { display: flex; gap: 16px; margin: 0 0 24px; font-size: 0.9rem; }
nav .brand { font-weight: 600; color: var(--text); text-decoration: none; margin-right: auto; }
form.search { display: flex; gap: 8px; flex-wrap: wrap; margin: 0 0 24px; }
form.search input[type="search"] {
  flex: 1 1 260px; min-width: 0; padding: 8px 12px; font: inherit; color: var(--text);
  background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
}
form.search button {
  padding: 8px 14px; font: inherit; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--border); background: var(--surface); color: var(--text);
}
form.search button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
form.search input.filter { flex: 0 1 200px; }
.filtered code {
  background: var(--surface); border: 1px solid var(--border); border-radius: 4px;
  padding: 0 4px; font-size: 0.85em;
}
"""


@dataclass(frozen=True)
class PageLinks:
    """Where the page's form and navigation point when it is served as a web UI."""

    search: str
    """Form action for searching; the query goes in the ``q`` parameter."""
    ask: str
    """Form action for asking Claude, with the question in ``q``."""
    dashboard: str
    source: str | None = None
    """Where the server serves indexed files to open from citations; without it, files
    are linked with ``file://`` URIs."""


class HtmlSearchRenderer:
    """Ranked passages with highlighted terms and a score breakdown bar chart per result.

    With ``links`` the page also carries a search form and navigation, so it doubles as the
    home page of the web UI; without them it is a standalone, shareable results page.
    Each passage's citation links to its source (see ``SourceLocator``); by default a
    text source opens at the passage itself (see ``HighlightingLocator``).
    """

    def __init__(
        self, links: PageLinks | None = None, locator: SourceLocator | None = None
    ) -> None:
        self._links = links
        self._locator = (
            locator if locator is not None else HighlightingLocator(FileAndUrlLocator())
        )

    def render(
        self, query: str, results: Sequence[SearchResult], source: SourceFilter | None = None
    ) -> str:
        wanted = source or SourceFilter()
        body: list[str] = []
        if self._links is not None:
            body.append(self._navigation(self._links))
            body.append(self._form(self._links, query, wanted))
        if query:
            body.append(
                f"<header>\n<h1>{escape(query)}</h1>\n"
                f'<p class="muted filtered">{self._summary(query, results, wanted)}</p>'
                "\n</header>"
            )
            body.extend(
                source_html(rank, result, passage_href(self._locator, result))
                for rank, result in enumerate(results, 1)
            )
        elif self._links is None:
            body.append('<h1>Search</h1>\n<p class="muted">No query.</p>')
        title = f"docsage: {query}" if query else "docsage"
        return page(title, "\n".join(body), REPORT_CSS + CHART_CSS + SEARCH_CSS)

    @staticmethod
    def _navigation(links: PageLinks) -> str:
        return (
            f'<nav><a class="brand" href="{escape(links.search)}">docsage</a>'
            f'<a href="{escape(links.dashboard)}">Dashboard</a></nav>'
        )

    @staticmethod
    def _form(links: PageLinks, query: str, wanted: SourceFilter) -> str:
        return (
            f'<form class="search" method="get" action="{escape(links.search)}" role="search">'
            f'<input type="search" name="q" value="{escape(query)}" required '
            'placeholder="Search your documents or ask a question" aria-label="Query">'
            f'<input class="filter" type="search" name="source" value="{escape(wanted.pattern)}" '
            'placeholder="Source: .md, docs/api" aria-label="Source filter" '
            'title="Search only part of the index: a file type, a folder or a URL prefix">'
            '<button class="primary" type="submit">Search</button>'
            f'<button type="submit" formaction="{escape(links.ask)}">Ask Claude</button>'
            "</form>"
        )

    def _summary(self, query: str, results: Sequence[SearchResult], wanted: SourceFilter) -> str:
        """How many passages matched, which part of the index was searched, and a way out."""
        if not wanted:
            return _count(len(results))
        where = f"<code>{escape(wanted.pattern.strip())}</code>"
        if results:
            summary = f"{_count(len(results))} in {where}"
        else:
            summary = f"No passage in {where} matches this query."
        if self._links is None:
            return summary
        unfiltered = f"{self._links.search}?{urlencode({'q': query})}"
        return f'{summary} · <a href="{escape(unfiltered)}">Search the whole index</a>'


def _count(results: int) -> str:
    if results == 0:
        return "No passage matches this query."
    return "1 matching passage" if results == 1 else f"{results} matching passages"
