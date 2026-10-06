"""Core domain entities. Pure data, no I/O and no third-party dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Document:
    """A source document loaded from disk."""

    source: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Chunk:
    """A contiguous slice of a document, the unit of retrieval."""

    id: str
    source: str
    text: str
    position: int
    content_hash: str = ""
    """Fingerprint of the whole source document, used to skip unchanged files."""


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
