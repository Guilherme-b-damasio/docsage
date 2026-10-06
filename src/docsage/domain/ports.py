"""Abstract ports the application layer depends on (Dependency Inversion).

Concrete adapters live in ``docsage.infrastructure`` and are wired together in
``docsage.container``. Each port is small and focused (Interface Segregation).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol

from docsage.domain.models import Chunk, Document, SearchResult


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

    def chunks(self) -> list[Chunk]: ...

    def __len__(self) -> int: ...


class IndexRepository(Protocol):
    """Persists and restores a retriever's state."""

    def save(self, retriever: Retriever) -> None: ...

    def load(self) -> Retriever: ...


class AnswerGenerator(Protocol):
    """Produces a natural-language answer grounded on retrieved context."""

    def generate(self, question: str, context: Sequence[SearchResult]) -> str: ...
