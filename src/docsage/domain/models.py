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

    @property
    def citation(self) -> str:
        """Human-readable location, e.g. ``guide.pdf, p. 3`` or ``guide.pdf, pp. 3-4``."""
        if self.first_page is None:
            return self.source
        if self.last_page is None or self.last_page == self.first_page:
            return f"{self.source}, p. {self.first_page}"
        return f"{self.source}, pp. {self.first_page}-{self.last_page}"


@dataclass(frozen=True)
class SearchResult:
    """A chunk paired with its relevance score for a query."""

    chunk: Chunk
    score: float


@dataclass(frozen=True)
class Answer:
    """A generated answer and the chunks it was grounded on."""

    question: str
    text: str
    sources: tuple[SearchResult, ...]
