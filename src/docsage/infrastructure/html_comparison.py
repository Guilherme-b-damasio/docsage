"""Renders two answers to the same question side by side on one offline HTML page."""

from __future__ import annotations

from html import escape

from docsage.domain.models import AnswerComparison, ComparedAnswer, SearchResult
from docsage.domain.ports import SourceLocator
from docsage.infrastructure.html_page import highlighted, page
from docsage.infrastructure.html_report import REPORT_CSS, answer_html
from docsage.infrastructure.source_links import (
    FileAndUrlLocator,
    HighlightingLocator,
    passage_href,
)
from docsage.infrastructure.units import plural, usage_summary

COMPARISON_CSS = """
main { max-width: 1200px; }
.sides { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
@media (max-width: 760px) { .sides { grid-template-columns: minmax(0, 1fr); } }
.side > h2 { margin-top: 16px; overflow-wrap: anywhere; }
.side .source.shared { border-color: var(--accent); }
.badge {
  display: inline-block; border: 1px solid var(--accent); color: var(--accent);
  border-radius: 999px; padding: 0 8px; font-size: 0.75rem; margin-left: 6px;
}
.overlap .meter {
  height: 8px; border-radius: 999px; background: var(--grid); overflow: hidden; margin-top: 8px;
}
.overlap .meter span { display: block; height: 100%; background: var(--bar); }
"""

_SIDES = ("left", "right")


class HtmlComparisonRenderer:
    """The question, how many passages both answers share, then each answer in a column
    with the passages it cited; a passage the other side also retrieved is marked
    "in both". Columns stack on narrow screens, and the page follows light and dark mode.
    """

    def __init__(self, locator: SourceLocator | None = None) -> None:
        self._locator = (
            locator if locator is not None else HighlightingLocator(FileAndUrlLocator())
        )

    def render(self, comparison: AnswerComparison) -> str:
        shared = comparison.shared_chunks()
        columns = [
            self._side_html(side, anchor, shared)
            for side, anchor in zip((comparison.left, comparison.right), _SIDES, strict=True)
        ]
        body = [
            f"<header>\n<h1>{escape(comparison.question)}</h1>\n"
            f'<p class="muted">Answered twice by docsage: '
            f"{escape(comparison.left.label)} vs {escape(comparison.right.label)}</p>\n</header>",
            _overlap_html(comparison),
            '<div class="sides">\n' + "\n".join(columns) + "\n</div>",
        ]
        return page(
            f"docsage: {comparison.question} (compared)",
            "\n".join(body),
            REPORT_CSS + COMPARISON_CSS,
        )

    def _side_html(self, side: ComparedAnswer, anchor: str, shared: frozenset[str]) -> str:
        answer = side.answer
        passages = [
            self._passage_html(rank, result, anchor, result.chunk.id in shared)
            for rank, result in enumerate(answer.sources, start=1)
        ]
        usage = (
            f'<p class="muted">{escape(usage_summary(answer.usage, answer.cost_usd))}</p>'
            if answer.usage is not None
            else ""
        )
        return (
            f'<section class="side" aria-label="{escape(side.label)}">\n'
            f"<h2>{escape(side.label)}</h2>\n"
            f'<p class="muted">{plural(len(answer.sources), "passage")}</p>\n'
            f'<section class="card answer">\n{answer_html(answer, anchor)}\n</section>\n'
            + "\n".join(passages)
            + usage
            + "\n</section>"
        )

    def _passage_html(self, rank: int, result: SearchResult, anchor: str, shared: bool) -> str:
        citation = escape(result.chunk.citation)
        href = passage_href(self._locator, result)
        if href is not None:
            citation = (
                f'<a href="{escape(href)}" target="_blank" rel="noopener noreferrer" '
                f'title="Open the source">{citation}</a>'
            )
        badge = '<span class="badge">in both</span>' if shared else ""
        return (
            f'<article class="card source{" shared" if shared else ""}" id="{anchor}-{rank}">\n'
            f'<header><span class="rank">[{rank}] {citation}{badge}</span>'
            f'<span class="muted">score {result.score:.2f}</span></header>\n'
            f"<blockquote>{highlighted(result.chunk.text, result.highlights)}</blockquote>\n"
            "</article>"
        )


def _overlap_html(comparison: AnswerComparison) -> str:
    """How much the two sides' passages agree, in words and as a meter."""
    shared = len(comparison.shared_chunks())
    percent = round(comparison.overlap() * 100)
    return (
        '<section class="card overlap" aria-label="Passage overlap">'
        f"<strong>{plural(shared, 'passage')} in both answers</strong>"
        f'<span class="muted"> · {percent}% overlap</span>'
        f'<div class="meter" role="img" aria-label="{percent}% of the passages are shared">'
        f'<span style="width: {percent}%"></span></div></section>'
    )
