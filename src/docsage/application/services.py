"""Use cases. They orchestrate ports and know nothing about concrete adapters."""

from __future__ import annotations

import hashlib
import logging
import math
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from itertools import combinations
from pathlib import Path

from docsage.domain.models import (
    Answer,
    CaseOutcome,
    ChatTurn,
    Chunk,
    ChunkPoint,
    Document,
    DocumentRelation,
    EvaluationCase,
    EvaluationReport,
    HistogramBin,
    IndexOverview,
    SearchResult,
)
from docsage.domain.ports import (
    AnswerGenerator,
    AnswerRenderer,
    Chunker,
    ChunkProjector,
    ConversationalAnswerGenerator,
    DashboardRenderer,
    DocumentLoader,
    EvaluationRenderer,
    Highlighter,
    IndexRepository,
    Retriever,
    StreamingAnswerGenerator,
    TextTokenizer,
)

logger = logging.getLogger(__name__)

MIN_RELATION_TERM_LENGTH = 3


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


def _highlighted(
    results: Sequence[SearchResult], query: str, highlighter: Highlighter | None
) -> list[SearchResult]:
    """Attaches the query's matches to each result when a highlighter is configured."""
    if highlighter is None:
        return list(results)
    return [
        replace(result, highlights=tuple(highlighter.highlight(query, result.chunk.text)))
        for result in results
    ]


class SearchService:
    """Ranks indexed chunks against a query without calling any model."""

    def __init__(self, retriever: Retriever, highlighter: Highlighter | None = None) -> None:
        self._retriever = retriever
        self._highlighter = highlighter

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        results = _highlighted(self._retriever.search(query, top_k), query, self._highlighter)
        logger.debug("searched index", extra={"top_k": top_k, "results": len(results)})
        return results


class EvaluationService:
    """Measures how well the retriever finds the labeled relevant documents of each query."""

    def __init__(self, retriever: Retriever, renderer: EvaluationRenderer) -> None:
        self._retriever = retriever
        self._renderer = renderer

    def evaluate(self, cases: Sequence[EvaluationCase], k: int = 5) -> EvaluationReport:
        if k < 1:
            raise ValueError("k must be at least 1")
        outcomes = tuple(self._outcome(case, k) for case in cases)
        logger.debug("evaluated retrieval", extra={"queries": len(outcomes), "k": k})
        return EvaluationReport(k, outcomes)

    def render(self, report: EvaluationReport) -> str:
        return self._renderer.render(report)

    def _outcome(self, case: EvaluationCase, k: int) -> CaseOutcome:
        sources = tuple(result.chunk.source for result in self._retriever.search(case.query, k))
        relevant = set(case.relevant)
        found: set[str] = set()
        first_hit = None
        curve = []
        for cut in range(k):
            if cut < len(sources):
                hits = {label for label in relevant if source_matches(sources[cut], label)}
                if hits and first_hit is None:
                    first_hit = cut + 1
                found |= hits
            curve.append(len(found) / len(relevant) if relevant else 0.0)
        return CaseOutcome(case, sources, first_hit, tuple(curve))


def source_matches(source: str, label: str) -> bool:
    """True when ``label`` is ``source`` itself or a trailing part of its path.

    Separators are normalized, so ``docs/faq.md`` matches ``C:\\notes\\docs\\faq.md`` but
    ``faq.md`` does not match ``myfaq.md``.
    """
    path = source.replace("\\", "/")
    wanted = label.replace("\\", "/").strip("/")
    return bool(wanted) and (path == wanted or path.endswith("/" + wanted))


class QuestionAnsweringService:
    """Retrieves relevant chunks and asks the generator for a grounded answer."""

    def __init__(
        self,
        retriever: Retriever,
        generator: AnswerGenerator,
        highlighter: Highlighter | None = None,
    ) -> None:
        self._retriever = retriever
        self._generator = generator
        self._highlighter = highlighter

    def ask(
        self,
        question: str,
        top_k: int = 5,
        on_text: Callable[[str], None] | None = None,
    ) -> Answer:
        """``on_text`` receives the answer's text as it is generated: piece by piece when the
        generator can stream, otherwise all at once when it is ready."""
        results = _highlighted(
            self._retriever.search(question, top_k), question, self._highlighter
        )
        logger.debug("retrieved context", extra={"top_k": top_k, "results": len(results)})
        if not results:
            if on_text:
                on_text(NO_CONTEXT_ANSWER)
            return Answer(question, NO_CONTEXT_ANSWER, ())
        text = self._generate(question, results, on_text)
        logger.debug("generated answer", extra={"characters": len(text)})
        return Answer(question, text, tuple(results))

    def _generate(
        self,
        question: str,
        results: Sequence[SearchResult],
        on_text: Callable[[str], None] | None,
    ) -> str:
        if on_text is None:
            return self._generator.generate(question, results)
        if not isinstance(self._generator, StreamingAnswerGenerator):
            text = self._generator.generate(question, results)
            on_text(text)
            return text
        pieces = []
        for piece in self._generator.stream(question, results):
            pieces.append(piece)
            on_text(piece)
        return "".join(pieces)


NO_CONTEXT_ANSWER = "No relevant context found in the index."


class ChatService:
    """A conversation about the index: every question gets fresh passages, and the generator
    also sees the earlier turns so follow-ups like "and in version 2?" make sense.

    Only the last ``max_turns`` turns are sent along, so a long chat stays within budget.
    """

    def __init__(
        self,
        retriever: Retriever,
        generator: ConversationalAnswerGenerator,
        highlighter: Highlighter | None = None,
        max_turns: int = 10,
    ) -> None:
        if max_turns < 0:
            raise ValueError("max_turns must not be negative")
        self._retriever = retriever
        self._generator = generator
        self._highlighter = highlighter
        self._max_turns = max_turns
        self._history: list[ChatTurn] = []

    @property
    def history(self) -> tuple[ChatTurn, ...]:
        """Every turn so far, oldest first."""
        return tuple(self._history)

    def reset(self) -> None:
        """Forgets the conversation so the next question starts a new one."""
        self._history.clear()

    def ask(
        self,
        question: str,
        top_k: int = 5,
        on_text: Callable[[str], None] | None = None,
    ) -> Answer:
        """Answers ``question`` and remembers the turn; ``on_text`` receives the text as it is
        written. A question with no matching passages is answered without the generator and
        is not remembered."""
        results = _highlighted(
            self._retriever.search(question, top_k), question, self._highlighter
        )
        if not results:
            if on_text:
                on_text(NO_CONTEXT_ANSWER)
            return Answer(question, NO_CONTEXT_ANSWER, ())
        recent = self._history[-self._max_turns :] if self._max_turns else []
        pieces = []
        for piece in self._generator.converse(question, results, recent):
            pieces.append(piece)
            if on_text:
                on_text(piece)
        text = "".join(pieces)
        self._history.append(ChatTurn(question, text))
        logger.debug(
            "chat turn", extra={"turn": len(self._history), "context_turns": len(recent)}
        )
        return Answer(question, text, tuple(results))


@dataclass(frozen=True)
class AnswerReport:
    answer: Answer
    content: str
    """The rendered report, e.g. a complete HTML document."""


class AnswerReportService:
    """Answers a question and renders the answer with its cited passages as a report."""

    def __init__(self, answering: QuestionAnsweringService, renderer: AnswerRenderer) -> None:
        self._answering = answering
        self._renderer = renderer

    def report(self, question: str, top_k: int = 5) -> AnswerReport:
        answer = self._answering.ask(question, top_k)
        content = self._renderer.render(answer)
        logger.debug("rendered answer report", extra={"characters": len(content)})
        return AnswerReport(answer, content)


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


class RelationService:
    """Links documents that share characteristic terms.

    Each document is described by its ``terms_per_document`` most characteristic terms:
    frequent in the document (tf) but not in every document (smoothed idf). Very short
    terms and numbers say little about a topic and are left out. Two documents are
    related when those term sets overlap.
    """

    def __init__(
        self, retriever: Retriever, tokenizer: TextTokenizer, terms_per_document: int = 10
    ) -> None:
        self._retriever = retriever
        self._tokenizer = tokenizer
        self._terms_per_document = terms_per_document

    def top_terms(self) -> dict[str, tuple[str, ...]]:
        """Each document's characteristic terms, most characteristic first."""
        frequencies: dict[str, Counter[str]] = {}
        for chunk in self._retriever.chunks():
            terms = [term for term in self._tokenizer(chunk.text) if _is_descriptive(term)]
            frequencies.setdefault(chunk.source, Counter()).update(terms)
        documents = Counter(term for counts in frequencies.values() for term in counts)
        total = len(frequencies)
        top: dict[str, tuple[str, ...]] = {}
        for source, counts in frequencies.items():
            weights = {
                term: count * math.log((1 + total) / documents[term])
                for term, count in counts.items()
            }
            # Ties are broken alphabetically so the output is stable.
            ranked = sorted(weights.items(), key=lambda item: (-item[1], item[0]))
            top[source] = tuple(term for term, _ in ranked[: self._terms_per_document])
        return top

    def relations(self, limit: int = 30) -> tuple[DocumentRelation, ...]:
        """At most ``limit`` related pairs, the ones sharing most terms first."""
        top = self.top_terms()
        found = []
        for first, second in combinations(sorted(top), 2):
            ranks = {term: rank for rank, term in enumerate(top[first])}
            shared = sorted(set(top[first]) & set(top[second]), key=lambda term: ranks[term])
            if shared:
                found.append(DocumentRelation(first, second, tuple(shared)))
        found.sort(key=lambda relation: (-relation.strength, relation.first, relation.second))
        return tuple(found[:limit])


def _is_descriptive(term: str) -> bool:
    return len(term) >= MIN_RELATION_TERM_LENGTH and not term.isdigit()


class DashboardService:
    """Builds the index overview the dashboard shows and renders it."""

    def __init__(
        self,
        stats: StatsService,
        retriever: Retriever,
        renderer: DashboardRenderer,
        relations: RelationService | None = None,
        projector: ChunkProjector | None = None,
    ) -> None:
        """Without ``relations`` the overview has no document relationships, and without
        ``projector`` it has no chunk map."""
        self._stats = stats
        self._retriever = retriever
        self._renderer = renderer
        self._relations = relations
        self._projector = projector

    def overview(self, top: int = 15, bins: int = 10) -> IndexOverview:
        stats = self._stats.stats(top)
        chunks = self._retriever.chunks()
        types = Counter(file_type(source) for source in {chunk.source for chunk in chunks})
        return IndexOverview(
            documents=stats.documents,
            chunks=stats.chunks,
            terms=stats.terms,
            vocabulary=stats.vocabulary,
            index_bytes=stats.index_bytes,
            documents_by_type=tuple(sorted(types.items(), key=lambda item: (-item[1], item[0]))),
            chunk_lengths=histogram([len(chunk.text.split()) for chunk in chunks], bins),
            top_terms=stats.top_terms,
            relations=self._relations.relations() if self._relations else (),
            chunk_map=self._chunk_map(chunks),
        )

    def _chunk_map(self, chunks: Sequence[Chunk]) -> tuple[ChunkPoint, ...]:
        if self._projector is None or not chunks:
            return ()
        points = tuple(self._projector.project(chunks))
        logger.debug("projected chunks", extra={"points": len(points)})
        return points

    def render(self, top: int = 15, bins: int = 10) -> str:
        return self.render_overview(self.overview(top, bins))

    def render_overview(self, overview: IndexOverview) -> str:
        """Renders an overview built earlier, e.g. to show it in several formats."""
        return self._renderer.render(overview)


def file_type(source: str) -> str:
    """Lower-case extension without the dot, e.g. ``md``; ``other`` when there is none."""
    return Path(source).suffix.lower().lstrip(".") or "other"


def histogram(values: Sequence[int], bins: int) -> tuple[HistogramBin, ...]:
    """Splits ``values`` into at most ``bins`` equal-width integer ranges.

    Every range is kept, even when empty, so gaps in the distribution stay visible.
    """
    if not values:
        return ()
    if bins < 1:
        raise ValueError("bins must be at least 1")
    low, high = min(values), max(values)
    width = max(1, -(-(high - low + 1) // bins))
    edges = range(low, high + 1, width)
    counts = Counter((value - low) // width for value in values)
    return tuple(
        HistogramBin(start, min(start + width - 1, high), counts[index])
        for index, start in enumerate(edges)
    )


@dataclass(frozen=True)
class DocumentSummary:
    source: str
    chunk_ids: tuple[str, ...]
    """Ids of the document's chunks in reading order."""
    pages: int | None
    """Last page seen in the document's chunks, None for unpaged formats."""
    sections: tuple[str, ...]
    """Distinct heading paths in reading order (Markdown only)."""

    @property
    def chunks(self) -> int:
        return len(self.chunk_ids)


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
        chunk_ids=tuple(chunk.id for chunk in ordered),
        pages=max(pages) if pages else None,
        sections=tuple(sections),
    )
