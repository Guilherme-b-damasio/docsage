"""Renders an answer as a self-contained HTML report with highlighted citations."""

from __future__ import annotations

import re
from html import escape

from docsage.domain.models import Answer, SearchResult, TokenUsage
from docsage.domain.ports import SourceLocator
from docsage.infrastructure.html_page import highlighted, page
from docsage.infrastructure.source_links import FileAndUrlLocator
from docsage.infrastructure.svg_charts import CHART_CSS, bar_chart, data_table
from docsage.infrastructure.units import usage_summary

_CITATION = re.compile(r"\[(\d+)\]")

REPORT_CSS = """
.answer p { margin: 0 0 12px; }
.answer p:last-child { margin-bottom: 0; }
.cite { text-decoration: none; font-weight: 600; }
.source header { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.source .rank { font-weight: 600; }
.source .rank a { color: inherit; text-decoration-color: var(--border); }
.source .rank a:hover { color: var(--accent); text-decoration-color: currentColor; }
.source blockquote {
  margin: 8px 0 0; padding-left: 12px; border-left: 3px solid var(--border);
  white-space: pre-wrap; overflow-wrap: anywhere;
}
.terms { margin-top: 8px; }
.term {
  display: inline-block; border: 1px solid var(--border); border-radius: 999px;
  padding: 0 8px; margin: 0 4px 4px 0; font-size: 0.8rem; color: var(--muted);
}
.breakdown { margin-top: 12px; }
.breakdown h3 { font-size: 0.9rem; font-weight: 600; margin: 0 0 8px; color: var(--muted); }
"""


def _score_label(value: float) -> str:
    return f"{value:.2f}"


class HtmlAnswerRenderer:
    """Question, answer and cited passages on one offline page, light and dark aware.

    Inline citations such as ``[2]`` link to the matching passage, each passage links to
    its source (file, PDF page or URL) through ``locator``, and every query term found in
    a passage is wrapped in ``<mark>``.
    """

    def __init__(self, locator: SourceLocator | None = None) -> None:
        self._locator = locator if locator is not None else FileAndUrlLocator()

    def render(self, answer: Answer) -> str:
        body = [
            f"<header>\n<h1>{escape(answer.question)}</h1>\n"
            f'<p class="muted">Answered from {_plural(len(answer.sources), "passage")} '
            "by docsage</p>\n</header>",
            '<section class="card answer" aria-label="Answer">\n'
            f"{self._answer_html(answer)}\n</section>",
        ]
        if answer.sources:
            body.append("<h2>Sources</h2>")
            body.extend(
                source_html(rank, result, self._locator.href(result.chunk))
                for rank, result in enumerate(answer.sources, start=1)
            )
        if answer.usage is not None:
            body.append(usage_html(answer.usage, answer.cost_usd))
        return page(f"docsage: {answer.question}", "\n".join(body), REPORT_CSS + CHART_CSS)

    def _answer_html(self, answer: Answer) -> str:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", answer.text) if part.strip()]
        return "\n".join(
            f"<p>{self._link_citations(escape(paragraph), len(answer.sources))}</p>"
            for paragraph in paragraphs
        )

    @staticmethod
    def _link_citations(escaped: str, sources: int) -> str:
        def link(match: re.Match[str]) -> str:
            number = int(match.group(1))
            if not 1 <= number <= sources:
                return match.group(0)
            return f'<a class="cite" href="#source-{number}">[{number}]</a>'

        return _CITATION.sub(link, escaped).replace("\n", "<br>")


def source_html(rank: int, result: SearchResult, href: str | None = None) -> str:
    """A ranked passage card: citation, score, highlighted text, terms and score breakdown.

    With ``href`` the citation links to the passage's source.
    """
    terms = "".join(f'<span class="term">{escape(term)}</span>' for term in result.matched_terms)
    terms_html = f'\n<div class="terms">{terms}</div>' if terms else ""
    citation = escape(result.chunk.citation)
    if href is not None:
        citation = (
            f'<a href="{escape(href)}" target="_blank" rel="noopener noreferrer" '
            f'title="Open the source">{citation}</a>'
        )
    return (
        f'<article class="card source" id="source-{rank}">\n'
        f'<header><span class="rank">[{rank}] {citation}</span>'
        f'<span class="muted">score {result.score:.2f}</span></header>\n'
        f"<blockquote>{highlighted(result.chunk.text, result.highlights)}</blockquote>"
        f"{terms_html}{breakdown_html(rank, result)}\n</article>"
    )


def breakdown_html(rank: int, result: SearchResult) -> str:
    """A bar per query term showing how much it added to the result's score."""
    if not result.contributions:
        return ""
    rows = [(item.term, item.score) for item in result.contributions]
    return (
        '\n<section class="breakdown">'
        "<h3>Score breakdown</h3>"
        f"{bar_chart(rows, f'Score breakdown of source {rank}', _score_label)}"
        f"{data_table(('Term', 'Score'), rows, _score_label)}</section>"
    )


def usage_html(usage: TokenUsage, cost_usd: float | None) -> str:
    """A bar per kind of token the answer consumed, with the estimated cost underneath."""
    rows = [
        (name, float(count))
        for name, count in (
            ("Input", usage.input_tokens),
            ("Cache write", usage.cache_creation_input_tokens),
            ("Cache read", usage.cache_read_input_tokens),
            ("Output", usage.output_tokens),
        )
        if count
    ]
    return (
        '<h2>Usage</h2>\n<section class="card usage" aria-label="Token usage">'
        f'<p class="muted">{escape(usage_summary(usage, cost_usd))}</p>'
        f"{bar_chart(rows, 'Tokens used by the answer')}"
        f"{data_table(('Tokens', 'Count'), rows)}</section>"
    )


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
