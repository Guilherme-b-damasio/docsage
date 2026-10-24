"""A shareable HTML answer report: the cited documents travel inside the page.

The ordinary report links each passage to the file it came from, which only works on the
machine that holds the index. This renderer reads every cited document back and inlines
it, with the cited passages marked in place, so the report can be attached to an email or
committed to a repository and still show each citation in its context.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from html import escape

from docsage.domain.models import Answer, Chunk, Citation, Highlight, SearchResult
from docsage.domain.ports import Highlighter, SourceLocator, SourceTextReader
from docsage.domain.text import passage_span
from docsage.infrastructure.html_page import highlighted, page
from docsage.infrastructure.html_report import REPORT_CSS, answer_body
from docsage.infrastructure.html_source import SOURCE_CSS
from docsage.infrastructure.source_links import (
    FileAndUrlLocator,
    HighlightingLocator,
    passage_href,
)
from docsage.infrastructure.svg_charts import CHART_CSS
from docsage.infrastructure.units import plural

PASSAGE_PREFIX = "passage-"
"""Prefix of the anchor an inlined document gives the passage cited as ``[n]``."""

SELF_CONTAINED_CSS = """
.inlined > h3 { font-size: 0.95rem; margin: 24px 0 4px; overflow-wrap: anywhere; }
.inlined > p { margin: 0 0 8px; font-size: 0.85rem; color: var(--muted); }
.anchor { display: block; height: 0; scroll-margin-top: 24px; }
"""


@dataclass(frozen=True)
class _Segment:
    """A stretch of a document covered by one cited passage, or by overlapping ones."""

    start: int
    end: int
    ranks: tuple[int, ...]
    highlights: tuple[Highlight, ...]
    """Matched terms inside the stretch, as offsets from ``start``."""


@dataclass(frozen=True)
class _Inlined:
    """One cited document's text, the stretches its passages cover and their anchors."""

    source: str
    text: str
    segments: tuple[_Segment, ...]
    anchors: dict[str, str]
    """Anchor inside this report for each cited chunk id, e.g. ``#passage-2``."""


class SelfContainedHtmlAnswerRenderer:
    """The answer report plus a copy of every document it cites, on one offline page.

    Each inlined citation links to the copy inside the report instead of to the file on
    disk, so a shared report needs no access to the machine that answered it. Sources that
    cannot be read back (web pages, formats no loader handles, files that are gone) keep
    the ordinary link, as do documents whose text no longer holds the cited passage, which
    are left out rather than inlined without the citation marked.
    """

    def __init__(self, reader: SourceTextReader, highlighter: Highlighter | None = None) -> None:
        self._reader = reader
        self._highlighter = highlighter
        self._fallback: SourceLocator = HighlightingLocator(FileAndUrlLocator())

    def render(self, answer: Answer) -> str:
        inlined = self._inlined(answer)
        anchors = {chunk: anchor for item in inlined for chunk, anchor in item.anchors.items()}
        body = answer_body(answer, _InlinedLocator(anchors, self._fallback))
        if inlined:
            body.append("<h2>Documents</h2>")
            body.append(
                f'<p class="muted">{plural(len(inlined), "cited document")} inlined below,'
                " so every citation can be read in its context without reaching the"
                " machine this report was written on.</p>"
            )
            body.extend(_inlined_html(item) for item in inlined)
        css = REPORT_CSS + CHART_CSS + SOURCE_CSS + SELF_CONTAINED_CSS
        return page(f"docsage: {answer.question}", "\n".join(body), css)

    def _inlined(self, answer: Answer) -> tuple[_Inlined, ...]:
        """Every cited document that could be read back, in the order the report shows."""
        documents = []
        for document in answer.cited_documents():
            text = self._reader.text(document.source)
            if text is None:
                continue
            segments = self._segments(text, document.citations)
            if not segments:
                continue
            anchors = {
                cited.result.chunk.id: _anchor(cited.rank)
                for cited in document.citations
                if any(cited.rank in segment.ranks for segment in segments)
            }
            documents.append(_Inlined(document.source, text, segments, anchors))
        return tuple(documents)

    def _segments(self, text: str, citations: Sequence[Citation]) -> tuple[_Segment, ...]:
        """The cited passages found in ``text``, in text order, overlapping ones merged.

        A sliding window lets two cited passages overlap, and one marked stretch cannot
        overlap another, so both passages' anchors point at the stretch covering them.
        Passages the document no longer holds, after an edit, are left unmarked.
        """
        found = []
        for cited in citations:
            span = passage_span(text, cited.result.chunk.text)
            if span is not None:
                found.append((span, cited))
        found.sort(key=lambda item: item[0])
        segments: list[_Segment] = []
        for (start, end), cited in found:
            highlights = self._highlights(text[start:end], cited.result)
            previous = segments[-1] if segments else None
            if previous is not None and start < previous.end:
                segments[-1] = _widened(previous, end, cited.rank)
                continue
            segments.append(_Segment(start, end, (cited.rank,), highlights))
        return tuple(segments)

    def _highlights(self, passage: str, result: SearchResult) -> tuple[Highlight, ...]:
        """The passage's matched terms found again in the document's own text.

        The chunker normalized the stored passage's whitespace, so the offsets it carries
        do not fit the document; the terms are located in the document's text instead.
        """
        terms = " ".join(result.matched_terms)
        if self._highlighter is None or not terms.strip():
            return ()
        return tuple(self._highlighter.highlight(terms, passage))


def _widened(segment: _Segment, end: int, rank: int) -> _Segment:
    """``segment`` grown over an overlapping passage, carrying that passage's rank too.

    The highlights of the overlapping passage are dropped: they were found in its own
    slice of the document, where ``highlighted`` would read them as overlapping spans.
    """
    return _Segment(
        segment.start, max(segment.end, end), segment.ranks + (rank,), segment.highlights
    )


def _inlined_html(item: _Inlined) -> str:
    """One document's text with the cited stretches set off, anchored and linked back."""
    ranks = sorted({rank for segment in item.segments for rank in segment.ranks})
    links = ", ".join(f'<a href="#source-{rank}">[{rank}]</a>' for rank in ranks)
    return (
        '<section class="inlined">\n'
        f"<h3>{escape(item.source)}</h3>\n"
        f"<p>{plural(len(ranks), 'passage')} cited, back to {links}</p>\n"
        f'<div class="document card">\n{_text_html(item)}\n</div>\n</section>'
    )


def _text_html(item: _Inlined) -> str:
    """The document split into what lies between the cited stretches and the stretches."""
    parts = []
    cursor = 0
    for segment in item.segments:
        parts.append(_plain(item.text[cursor : segment.start]))
        parts.append(_passage(item.text[segment.start : segment.end], segment))
        cursor = segment.end
    parts.append(_plain(item.text[cursor:]))
    return "\n".join(part for part in parts if part)


def _passage(text: str, segment: _Segment) -> str:
    anchors = "".join(
        f'<span class="anchor" id="{PASSAGE_PREFIX}{rank}"></span>' for rank in segment.ranks
    )
    return (
        f'{anchors}<pre class="passage" tabindex="-1">{highlighted(text, segment.highlights)}</pre>'
    )


def _plain(text: str) -> str:
    return f"<pre>{escape(text)}</pre>" if text else ""


def _anchor(rank: int) -> str:
    return f"#{PASSAGE_PREFIX}{rank}"


class _InlinedLocator:
    """Points an inlined passage at its copy in the report, the rest at ``fallback``."""

    def __init__(self, anchors: dict[str, str], fallback: SourceLocator) -> None:
        self._anchors = anchors
        self._fallback = fallback

    def href(self, chunk: Chunk) -> str | None:
        anchor = self._anchors.get(chunk.id)
        return anchor if anchor is not None else self._fallback.href(chunk)

    def passage_href(self, result: SearchResult) -> str | None:
        anchor = self._anchors.get(result.chunk.id)
        return anchor if anchor is not None else passage_href(self._fallback, result)
