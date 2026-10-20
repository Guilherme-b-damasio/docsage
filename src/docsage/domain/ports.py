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
    ChatTurn,
    Chunk,
    ChunkPoint,
    Document,
    EvaluationReport,
    FileChanges,
    Highlight,
    IndexOverview,
    SearchResult,
    TokenUsage,
)


class DocumentLoader(Protocol):
    """Reads one kind of file into a ``Document``."""

    def supports(self, path: Path) -> bool: ...

    def load(self, path: Path) -> Document: ...


class UrlLoader(Protocol):
    """Fetches one web page into a ``Document`` whose source is the page's URL."""

    def load(self, url: str) -> Document:
        """Raises ``OSError`` when the page cannot be fetched and ``ValueError`` when
        its content cannot be indexed."""
        ...


class FileWatcher(Protocol):
    """Reports file changes under folders as they happen."""

    def watch(self, roots: Sequence[Path]) -> Iterator[FileChanges]:
        """Yields one batch per detected change, forever; the first batch lists every
        file already present, so a fresh watch also picks up what changed while nobody
        was watching."""
        ...


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


@runtime_checkable
class ConversationalAnswerGenerator(Protocol):
    """Answers a question in the light of the earlier turns of a conversation."""

    def converse(
        self, question: str, context: Sequence[SearchResult], history: Sequence[ChatTurn]
    ) -> Iterator[str]:
        """Yields the answer's text in order, as it is written; ``history`` is oldest first."""
        ...


@runtime_checkable
class UsageReportingGenerator(Protocol):
    """A generator that can tell how many tokens its most recent answer consumed."""

    @property
    def last_usage(self) -> TokenUsage | None:
        """Usage of the last finished answer (None before the first one)."""
        ...


class CostEstimator(Protocol):
    """Prices the tokens an answer consumed."""

    def estimate(self, usage: TokenUsage) -> float | None:
        """Cost in US dollars, or None when the model's price is unknown."""
        ...


class Highlighter(Protocol):
    """Finds where a query's terms occur in a passage, for highlighted citations."""

    def highlight(self, query: str, text: str) -> list[Highlight]: ...


class SourceLocator(Protocol):
    """Points at where a passage can be opened: its file, page or web address."""

    def href(self, chunk: Chunk) -> str | None:
        """A link to the chunk's source, or None when it cannot be linked."""
        ...


class AnswerRenderer(Protocol):
    """Turns an answer and its cited passages into a shareable report (HTML, text...)."""

    def render(self, answer: Answer) -> str: ...


class SearchRenderer(Protocol):
    """Turns a query and its ranked passages into a results page (HTML, text...)."""

    def render(self, query: str, results: Sequence[SearchResult]) -> str: ...


class DashboardRenderer(Protocol):
    """Turns an overview of the index into a dashboard (HTML, text...)."""

    def render(self, overview: IndexOverview) -> str: ...


class EvaluationRenderer(Protocol):
    """Turns a retrieval evaluation into a report (HTML, text...)."""

    def render(self, report: EvaluationReport) -> str: ...
