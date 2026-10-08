"""Use cases. They orchestrate ports and know nothing about concrete adapters."""

from __future__ import annotations

import hashlib
import logging
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from docsage.domain.models import Answer, Chunk, Document, SearchResult
from docsage.domain.ports import (
    AnswerGenerator,
    Chunker,
    DocumentLoader,
    IndexRepository,
    Retriever,
    TextTokenizer,
)

logger = logging.getLogger(__name__)


class UnsupportedFileError(ValueError):
    """Raised when no loader can handle a file."""


@dataclass(frozen=True)
class IndexingReport:
    documents: int
    chunks: int
    skipped: tuple[str, ...]
    unchanged: int = 0


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

    def index(self, paths: Iterable[Path], force: bool = False) -> IndexingReport:
        """Indexes ``paths``; files whose content is already indexed are skipped
        unless ``force`` is set."""
        known = {} if force else self._known_hashes()
        documents = chunks = unchanged = 0
        skipped: list[str] = []
        for path in paths:
            try:
                document = self._load(path)
            except UnsupportedFileError:
                logger.debug("skipped unsupported file", extra={"path": str(path)})
                skipped.append(str(path))
                continue
            digest = content_hash(document)
            if known.get(document.source) == digest:
                logger.debug("skipped unchanged document", extra={"source": document.source})
                unchanged += 1
                continue
            new_chunks = [
                replace(chunk, content_hash=digest) for chunk in self._chunker.split(document)
            ]
            self._retriever.remove(document.source)
            self._retriever.add(new_chunks)
            logger.debug(
                "indexed document",
                extra={"source": document.source, "chunks": len(new_chunks)},
            )
            documents += 1
            chunks += len(new_chunks)
        if documents:
            self._repository.save(self._retriever)
        logger.info(
            "indexing finished",
            extra={
                "documents": documents,
                "chunks": chunks,
                "unchanged": unchanged,
                "skipped": len(skipped),
            },
        )
        return IndexingReport(documents, chunks, tuple(skipped), unchanged)

    def _known_hashes(self) -> dict[str, str]:
        return {chunk.source: chunk.content_hash for chunk in self._retriever.chunks()}

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
        logger.info(
            "removal finished",
            extra={"path": str(path), "documents": len(matched), "chunks": chunks},
        )
        if matched:
            self._repository.save(self._retriever)
        return RemovalReport(matched, chunks)


def _is_within(candidate: Path, target: Path) -> bool:
    return candidate == target or target in candidate.parents


def content_hash(document: Document) -> str:
    return hashlib.sha256(document.text.encode("utf-8")).hexdigest()


class SearchService:
    """Ranks indexed chunks against a query without calling any model."""

    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        results = self._retriever.search(query, top_k)
        logger.debug("searched index", extra={"top_k": top_k, "results": len(results)})
        return results


class QuestionAnsweringService:
    """Retrieves relevant chunks and asks the generator for a grounded answer."""

    def __init__(self, retriever: Retriever, generator: AnswerGenerator) -> None:
        self._retriever = retriever
        self._generator = generator

    def ask(self, question: str, top_k: int = 5) -> Answer:
        results = self._retriever.search(question, top_k)
        logger.debug("retrieved context", extra={"top_k": top_k, "results": len(results)})
        if not results:
            return Answer(question, "No relevant context found in the index.", ())
        text = self._generator.generate(question, results)
        logger.debug("generated answer", extra={"characters": len(text)})
        return Answer(question, text, tuple(results))


@dataclass(frozen=True)
class IndexStats:
    documents: int
    chunks: int
    terms: int
    """Indexed terms summed over chunks (overlapping windows count twice)."""
    vocabulary: int
    top_terms: tuple[tuple[str, int], ...]
    index_bytes: int


class StatsService:
    """Summarizes what is in the index."""

    def __init__(
        self, retriever: Retriever, tokenizer: TextTokenizer, repository: IndexRepository
    ) -> None:
        self._retriever = retriever
        self._tokenizer = tokenizer
        self._repository = repository

    def stats(self, top: int = 10) -> IndexStats:
        chunks = self._retriever.chunks()
        frequencies: Counter[str] = Counter()
        for chunk in chunks:
            frequencies.update(self._tokenizer(chunk.text))
        # Ties are broken alphabetically so the output is stable.
        ranked = sorted(frequencies.items(), key=lambda item: (-item[1], item[0]))
        return IndexStats(
            documents=len({chunk.source for chunk in chunks}),
            chunks=len(chunks),
            terms=sum(frequencies.values()),
            vocabulary=len(frequencies),
            top_terms=tuple(ranked[:top]),
            index_bytes=self._repository.size_bytes(),
        )


@dataclass(frozen=True)
class DocumentSummary:
    source: str
    chunks: int
    pages: int | None
    """Last page seen in the document's chunks, None for unpaged formats."""
    sections: tuple[str, ...]
    """Distinct heading paths in reading order (Markdown only)."""


class CatalogService:
    """Lists indexed documents and looks up their chunks."""

    def __init__(self, retriever: Retriever) -> None:
        self._retriever = retriever

    def documents(self) -> list[DocumentSummary]:
        by_source: dict[str, list[Chunk]] = {}
        for chunk in self._retriever.chunks():
            by_source.setdefault(chunk.source, []).append(chunk)
        return [_summarize(source, by_source[source]) for source in sorted(by_source)]

    def document_chunks(self, source: str) -> list[Chunk]:
        """Chunks of ``source`` in reading order, empty when it is not indexed."""
        chunks = [chunk for chunk in self._retriever.chunks() if chunk.source == source]
        return sorted(chunks, key=lambda chunk: chunk.position)

    def chunk(self, chunk_id: str) -> Chunk | None:
        return next((chunk for chunk in self._retriever.chunks() if chunk.id == chunk_id), None)


def _summarize(source: str, chunks: list[Chunk]) -> DocumentSummary:
    ordered = sorted(chunks, key=lambda chunk: chunk.position)
    pages = [page for chunk in ordered for page in (chunk.first_page, chunk.last_page) if page]
    sections = dict.fromkeys(chunk.section for chunk in ordered if chunk.section)
    return DocumentSummary(
        source=source,
        chunks=len(ordered),
        pages=max(pages) if pages else None,
        sections=tuple(sections),
    )
