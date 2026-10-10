"""Abstract ports the application layer depends on (Dependency Inversion).

Concrete adapters live in ``docsage.infrastructure`` and are wired together in
``docsage.container``. Each port is small and focused (Interface Segregation).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol

from docsage.domain.models import Answer, Chunk, Document, Highlight, SearchResult


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


class Highlighter(Protocol):
    """Finds where a query's terms occur in a passage, for highlighted citations."""

    def highlight(self, query: str, text: str) -> list[Highlight]: ...


class AnswerRenderer(Protocol):
    """Turns an answer and its cited passages into a shareable report (HTML, text...)."""

    def render(self, answer: Answer) -> str: ...
