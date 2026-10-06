"""Use cases. They orchestrate ports and know nothing about concrete adapters."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from docsage.domain.models import Answer, Document
from docsage.domain.ports import (
    AnswerGenerator,
    Chunker,
    DocumentLoader,
    IndexRepository,
    Retriever,
)


class UnsupportedFileError(ValueError):
    """Raised when no loader can handle a file."""


@dataclass(frozen=True)
class IndexingReport:
    documents: int
    chunks: int
    skipped: tuple[str, ...]


class IndexingService:
    """Loads files, splits them into chunks and stores them in the index."""

    def __init__(
        self,
        loaders: Sequence[DocumentLoader],
        chunker: Chunker,
        retriever: Retriever,
        repository: IndexRepository,
    ) -> None:
        self._loaders = loaders
        self._chunker = chunker
        self._retriever = retriever
        self._repository = repository

    def index(self, paths: Iterable[Path]) -> IndexingReport:
        documents = chunks = 0
        skipped: list[str] = []
        for path in paths:
            try:
                document = self._load(path)
            except UnsupportedFileError:
                skipped.append(str(path))
                continue
            new_chunks = self._chunker.split(document)
            self._retriever.remove(document.source)
            self._retriever.add(new_chunks)
            documents += 1
            chunks += len(new_chunks)
        self._repository.save(self._retriever)
        return IndexingReport(documents, chunks, tuple(skipped))

    def _load(self, path: Path) -> Document:
        for loader in self._loaders:
            if loader.supports(path):
                return loader.load(path)
        raise UnsupportedFileError(f"No loader for {path.suffix or path.name}")


@dataclass(frozen=True)
class RemovalReport:
    documents: tuple[str, ...]
    chunks: int


class RemovalService:
    """Drops a file, or every file under a folder, from the index."""

    def __init__(self, retriever: Retriever, repository: IndexRepository) -> None:
        self._retriever = retriever
        self._repository = repository

    def remove(self, path: Path) -> RemovalReport:
        sources = sorted({chunk.source for chunk in self._retriever.chunks()})
        matched = tuple(source for source in sources if _is_within(Path(source), path))
        chunks = sum(self._retriever.remove(source) for source in matched)
        if matched:
            self._repository.save(self._retriever)
        return RemovalReport(matched, chunks)


def _is_within(candidate: Path, target: Path) -> bool:
    return candidate == target or target in candidate.parents


class QuestionAnsweringService:
    """Retrieves relevant chunks and asks the generator for a grounded answer."""

    def __init__(self, retriever: Retriever, generator: AnswerGenerator) -> None:
        self._retriever = retriever
        self._generator = generator

    def ask(self, question: str, top_k: int = 5) -> Answer:
        results = self._retriever.search(question, top_k)
        if not results:
            return Answer(question, "No relevant context found in the index.", ())
        text = self._generator.generate(question, results)
        return Answer(question, text, tuple(results))
