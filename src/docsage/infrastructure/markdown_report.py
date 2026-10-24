"""Markdown answer report, for notes, wikis and pull requests."""

from __future__ import annotations

import re

from docsage.domain.models import Answer, SearchResult
from docsage.domain.ports import SourceLocator
from docsage.infrastructure.source_links import (
    FileAndUrlLocator,
    HighlightingLocator,
    passage_href,
)
from docsage.infrastructure.text_report import breakdown, emphasized
from docsage.infrastructure.units import usage_summary

_CITATION = re.compile(r"\[(\d+)\](?!\()")
_LINK_TEXT_SPECIALS = re.compile(r"([\\\[\]])")


def _within(source: str) -> str:
    """Which part of the index an answer came from, when it was narrowed to one."""
    return f" in `{source.strip()}`" if source.strip() else ""


class MarkdownAnswerRenderer:
    """The answer with ``[n]`` linked to its passage, then each passage as a quote.

    Matched terms appear in ``**bold**`` and every passage's citation links to its source
    (see ``SourceLocator``), so the report reads the same on GitHub, in an editor or a wiki.
    By default a text source opens at the passage itself (see ``HighlightingLocator``).
    """

    def __init__(self, locator: SourceLocator | None = None) -> None:
        self._locator = (
            locator if locator is not None else HighlightingLocator(FileAndUrlLocator())
        )

    def render(self, answer: Answer) -> str:
        lines = [f"# {_one_line(answer.question)}", "", _linked(answer.text, answer.sources)]
        if answer.sources:
            lines += ["", f"## Sources{_within(answer.source)}"]
        for rank, result in enumerate(answer.sources, start=1):
            lines += ["", *self._source(rank, result)]
        if answer.usage is not None:
            lines += ["", "---", "", f"*Usage: {usage_summary(answer.usage, answer.cost_usd)}*"]
        return "\n".join(lines) + "\n"

    def _source(self, rank: int, result: SearchResult) -> list[str]:
        title = _LINK_TEXT_SPECIALS.sub(r"\\\1", result.chunk.citation)
        href = passage_href(self._locator, result)
        if href is not None:
            title = f"[{title}](<{href}>)"
        lines = [
            f'<a id="source-{rank}"></a>',
            "",
            f"### [{rank}] {title}",
            "",
            f"Score {result.score:.2f}",
            "",
            _quoted(emphasized(result.chunk.text, result.highlights)),
        ]
        if result.contributions:
            lines += ["", f"Score breakdown: `{breakdown(result.contributions)}`"]
        return lines


def _linked(text: str, sources: tuple[SearchResult, ...]) -> str:
    """Turns ``[n]`` into a link to the n-th passage when that passage exists."""

    def link(match: re.Match[str]) -> str:
        number = int(match.group(1))
        if not 1 <= number <= len(sources):
            return match.group(0)
        return f"[\\[{number}\\]](#source-{number})"

    return _CITATION.sub(link, text.strip())


def _quoted(text: str) -> str:
    return "\n".join(f"> {line}".rstrip() for line in text.strip().splitlines())


def _one_line(text: str) -> str:
    return " ".join(text.split())
