"""Core domain entities. Pure data, no I/O and no third-party dependencies."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Document:
    """A source document loaded from disk."""

    source: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)
    page_offsets: tuple[int, ...] = ()
    """Character offset where each page starts in ``text`` (empty for unpaged formats)."""

    def page_at(self, offset: int) -> int | None:
        """1-based page containing the character at ``offset``, or None if unpaged."""
        if not self.page_offsets:
            return None
        return bisect_right(self.page_offsets, offset) or 1


@dataclass(frozen=True)
class Chunk:
    """A contiguous slice of a document, the unit of retrieval."""

    id: str
    source: str
    text: str
    position: int
    content_hash: str = ""
    """Fingerprint of the whole source document, used to skip unchanged files."""
    first_page: int | None = None
    last_page: int | None = None
    section: str = ""
    """Heading path the chunk belongs to, e.g. ``Setup > Install`` (Markdown only)."""

    @property
    def citation(self) -> str:
        """Human-readable location, e.g. ``guide.pdf, p. 3`` or ``notes.md, Setup > Install``."""
        if self.section:
            return f"{self.source}, {self.section}"
        if self.first_page is None:
            return self.source
        if self.last_page is None or self.last_page == self.first_page:
            return f"{self.source}, p. {self.first_page}"
        return f"{self.source}, pp. {self.first_page}-{self.last_page}"


@dataclass(frozen=True)
class Highlight:
    """A span of a chunk's text that matched a query term."""

    start: int
    """Character offset where the match starts in ``Chunk.text``."""
    end: int
    """Character offset just past the match, so ``text[start:end]`` is the matched word."""
    term: str
    """Normalized query term the span matched, e.g. ``index`` for ``Index``."""


@dataclass(frozen=True)
class SearchResult:
    """A chunk paired with its relevance score for a query."""

    chunk: Chunk
    score: float
    highlights: tuple[Highlight, ...] = ()
    """Where the query terms occur in the chunk, in text order (empty if not computed)."""

    @property
    def matched_terms(self) -> tuple[str, ...]:
        """Distinct query terms found in the chunk, in order of first occurrence."""
        return tuple(dict.fromkeys(highlight.term for highlight in self.highlights))


@dataclass(frozen=True)
class Answer:
    """A generated answer and the chunks it was grounded on."""

    question: str
    text: str
    sources: tuple[SearchResult, ...]


@dataclass(frozen=True)
class HistogramBin:
    """Values ``low <= value <= high`` and how many fell in that range."""

    low: int
    high: int
    count: int


@dataclass(frozen=True)
class IndexOverview:
    """Everything the index dashboard shows, computed once from the stored chunks."""

    documents: int
    chunks: int
    terms: int
    vocabulary: int
    index_bytes: int
    documents_by_type: tuple[tuple[str, int], ...]
    """``(file type, documents)`` pairs, most common type first."""
    chunk_lengths: tuple[HistogramBin, ...]
    """Distribution of chunk lengths in words, in ascending ranges."""
    top_terms: tuple[tuple[str, int], ...]
