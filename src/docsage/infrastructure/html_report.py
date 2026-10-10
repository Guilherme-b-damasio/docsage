"""Renders an answer as a self-contained HTML report with highlighted citations."""

from __future__ import annotations

import re
from html import escape

from docsage.domain.models import Answer, SearchResult
from docsage.infrastructure.html_page import highlighted, page

_CITATION = re.compile(r"\[(\d+)\]")

REPORT_CSS = """
.answer p { margin: 0 0 12px; }
.answer p:last-child { margin-bottom: 0; }
.cite { text-decoration: none; font-weight: 600; }
.source header { display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }
.source .rank { font-weight: 600; }
.source blockquote {
  margin: 8px 0 0; padding-left: 12px; border-left: 3px solid var(--border);
  white-space: pre-wrap; overflow-wrap: anywhere;
}
.terms { margin-top: 8px; }
.term {
  display: inline-block; border: 1px solid var(--border); border-radius: 999px;
  padding: 0 8px; margin: 0 4px 4px 0; font-size: 0.8rem; color: var(--muted);
}
"""


class HtmlAnswerRenderer:
    """Question, answer and cited passages on one offline page, light and dark aware.

    Inline citations such as ``[2]`` link to the matching passage, and every query term
    found in a passage is wrapped in ``<mark>``.
    """

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
                self._source_html(rank, result)
                for rank, result in enumerate(answer.sources, start=1)
            )
        return page(f"docsage: {answer.question}", "\n".join(body), REPORT_CSS)

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

    @staticmethod
    def _source_html(rank: int, result: SearchResult) -> str:
        terms = "".join(
            f'<span class="term">{escape(term)}</span>' for term in result.matched_terms
        )
        terms_html = f'\n<div class="terms">{terms}</div>' if terms else ""
        return (
            f'<article class="card source" id="source-{rank}">\n'
            f'<header><span class="rank">[{rank}] {escape(result.chunk.citation)}</span>'
            f'<span class="muted">score {result.score:.2f}</span></header>\n'
            f"<blockquote>{highlighted(result.chunk.text, result.highlights)}</blockquote>"
            f"{terms_html}\n</article>"
        )


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"
