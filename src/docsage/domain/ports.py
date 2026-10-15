"""Abstract ports the application layer depends on (Dependency Inversion).

Concrete adapters live in ``docsage.infrastructure`` and are wired together in
``docsage.container``. Each port is small and focused (Interface Segregation).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path
from typing import Protocol, runtime_checkable

from docsage.domain.models import (
    Answer,
    Chunk,
    ChunkPoint,
    Document,
    EvaluationReport,
    Highlight,
    IndexOverview,
    SearchResult,
)


class DocumentLoader(Protocol):
    """Reads one kind of file into a ``Document``."""

    def supports(self, path: Path) -> bool: ...

    def load(self, path: Path) -> Document: ...


class Chunker(Protocol):
    """Splits a document into retrievable chunks."""

    def split(self, document: Document) -> list[Chunk]: ...


class Retriever(Protocol):
    """Stores chunks and returns the most relevant ones for a query."""

    def add(self, chunks: Iterable[Chunk]) -> None: ...

    def search(self, query: str, top_k: int) -> list[SearchResult]: ...

    def remove(self, source: str) -> int:
        """Drops every chunk of ``source`` and returns how many were removed."""
        ...

    def chunks(self) -> list[Chunk]: ...

    def __len__(self) -> int: ...


class Embedder(Protocol):
    """Turns texts into dense vectors whose cosine similarity reflects meaning."""

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class Reranker(Protocol):
    """Reorders a retriever's candidates by how well each one answers the query."""

    def rerank(self, query: str, candidates: Sequence[SearchResult]) -> list[SearchResult]:
        """Returns every candidate, most relevant first, scored on the reranker's scale."""
        ...


class ChunkProjector(Protocol):
    """Places chunks on a 2D map so that chunks with similar meaning end up close."""

    def project(self, chunks: Sequence[Chunk]) -> list[ChunkPoint]: ...


class TextTokenizer(Protocol):
    """Splits text into the normalized terms used for ranking."""

    def __call__(self, text: str) -> list[str]: ...


class IndexRepository(Protocol):
    """Persists and restores a retriever's state."""

    def save(self, retriever: Retriever) -> None: ...

    def load(self) -> Retriever: ...

    def size_bytes(self) -> int:
        """Storage used by the persisted index, 0 when nothing is stored yet."""
        ...


class AnswerGenerator(Protocol):
    """Produces a natural-language answer grounded on retrieved context."""

    def generate(self, question: str, context: Sequence[SearchResult]) -> str: ...


@runtime_checkable
class StreamingAnswerGenerator(AnswerGenerator, Protocol):
    """An answer generator that can also hand out the answer piece by piece as it is written."""

    def stream(self, question: str, context: Sequence[SearchResult]) -> Iterator[str]:
        """Yields the answer's text in order; joined, the pieces are the whole answer."""
        ...


class Highlighter(Protocol):
    """Finds where a query's terms occur in a passage, for highlighted citations."""

    def highlight(self, query: str, text: str) -> list[Highlight]: ...


class AnswerRenderer(Protocol):
    """Turns an answer and its cited passages into a shareable report (HTML, text...)."""

    def render(self, answer: Answer) -> str: ...


class DashboardRenderer(Protocol):
    """Turns an overview of the index into a dashboard (HTML, text...)."""

    def render(self, overview: IndexOverview) -> str: ...


class EvaluationRenderer(Protocol):
    """Turns a retrieval evaluation into a report (HTML, text...)."""

    def render(self, report: EvaluationReport) -> str: ...
