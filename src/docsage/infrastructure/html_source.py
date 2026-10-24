"""Renders an indexed text source as HTML with one cited passage marked in place.

The server renders the page itself, so a report's citation opens the document scrolled to
the passage with its matched terms highlighted in every browser, without relying on
support for `text fragments <https://wicg.github.io/scroll-to-text-fragment/>`_.
"""

from __future__ import annotations

from html import escape

from docsage.domain.models import Highlight, SourceView, is_url
from docsage.infrastructure.html_page import highlighted, page

RENDERABLE_SOURCES = (".md", ".markdown", ".txt", ".rst")
"""File types shown as text; other formats are left to the browser (PDFs, Word)."""

PASSAGE_ID = "passage"
"""Anchor a link appends so the browser scrolls straight to the cited passage."""

SOURCE_CSS = """
:root { --passage-bg: #fffdf0; --passage-edge: #d9b640; }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --passage-bg: #1d1a0f; --passage-edge: #8a7320; }
}
:root[data-theme="dark"] { --passage-bg: #1d1a0f; --passage-edge: #8a7320; }
.document { margin: 0; }
.document pre {
  margin: 0; padding: 4px 16px; font: 0.9rem/1.7 ui-monospace, SFMono-Regular, Menlo, monospace;
  white-space: pre-wrap; overflow-wrap: anywhere;
}
.document pre.passage {
  background: var(--passage-bg); border-left: 3px solid var(--passage-edge);
  padding: 12px 16px; margin: 4px 0; scroll-margin-top: 24px;
}
.skip { display: inline-block; margin: 0 0 16px; font-size: 0.9rem; }
"""


class HtmlSourceRenderer:
    """One indexed document on a self-contained page, the cited passage set off in place.

    The text is shown as it was indexed, split into what comes before the passage, the
    passage itself (with its matched terms in ``<mark>``) and what comes after, so the
    reader sees the citation in its context. A viewer jumps to the passage with the
    ``#passage`` anchor; formats this renderer cannot show (see ``supports``) are served
    as files instead.
    """

    def supports(self, source: str) -> bool:
        return not is_url(source) and source.lower().endswith(RENDERABLE_SOURCES)

    def render(self, view: SourceView) -> str:
        body = [
            f"<header>\n<h1>{escape(view.source)}</h1>\n"
            f'<p class="muted">{_summary(view)}</p>\n</header>',
        ]
        if view.passage:
            body.append(f'<a class="skip" href="#{PASSAGE_ID}">Jump to the cited passage</a>')
        body.append(f'<div class="document card">\n{self._text_html(view)}\n</div>')
        return page(f"docsage: {view.source}", "\n".join(body), SOURCE_CSS)

    @staticmethod
    def _text_html(view: SourceView) -> str:
        start, end = view.passage_start, view.passage_end
        if start is None or end is None:
            return f"<pre>{escape(view.text)}</pre>"
        shifted = [
            Highlight(highlight.start - start, highlight.end - start, highlight.term)
            for highlight in _inside_passage(view)
        ]
        return "\n".join(
            [
                f"<pre>{escape(view.text[:start])}</pre>",
                f'<pre class="passage" id="{PASSAGE_ID}" tabindex="-1">'
                f"{highlighted(view.passage, shifted)}</pre>",
                f"<pre>{escape(view.text[end:])}</pre>",
            ]
        )


def _inside_passage(view: SourceView) -> list[Highlight]:
    """The highlights that fall inside the marked passage; the others are ignored."""
    start, end = view.passage_start, view.passage_end
    if start is None or end is None:
        return []
    return [
        highlight
        for highlight in view.highlights
        if start <= highlight.start and highlight.end <= end
    ]


def _summary(view: SourceView) -> str:
    if not view.passage:
        return "Indexed by docsage."
    terms = len({highlight.term for highlight in _inside_passage(view)})
    if not terms:
        return "The cited passage is highlighted below."
    return (
        f"The cited passage is highlighted below, with its "
        f"{'matched term' if terms == 1 else f'{terms} matched terms'} marked."
    )
