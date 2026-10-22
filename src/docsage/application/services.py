"""Use cases. They orchestrate ports and know nothing about concrete adapters."""

from __future__ import annotations

import hashlib
import logging
import math
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
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
    FileChanges,
    HistogramBin,
    IndexOverview,
    SearchResult,
    is_url,
)
from docsage.domain.ports import (
    AnswerGenerator,
    AnswerRenderer,
    Chunker,
    ChunkProjector,
    ConversationalAnswerGenerator,
    CostEstimator,
    DashboardRenderer,
    DocumentLoader,
    EvaluationRenderer,
    FileWatcher,
    Highlighter,
    IndexRepository,
    Retriever,
    SearchRenderer,
    StreamingAnswerGenerator,
    TextTokenizer,
    UrlLoader,
    UsageReportingGenerator,
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
    failed: tuple[tuple[str, str], ...] = ()
    """Web pages that could not be indexed, as ``(url, reason)`` pairs."""

    def combined_with(self, other: IndexingReport) -> IndexingReport:
        """The totals of two indexing runs, e.g. of local files and of web pages."""
        return IndexingReport(
            self.documents + other.documents,
            self.chunks + other.chunks,
            self.skipped + other.skipped,
            self.unchanged + other.unchanged,
            self.failed + other.failed,
        )


class IndexingService:
    """Loads files or web pages, splits them into chunks and stores them in the index."""

    def __init__(
        self,
        loaders: Sequence[DocumentLoader],
        chunker: Chunker,
        retriever: Retriever,
        repository: IndexRepository,
        url_loader: UrlLoader | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """Without a ``url_loader``, ``index_urls`` reports every URL as failed.
        ``clock`` tells when documents are indexed (the current UTC time by default)."""
        self._loaders = loaders
        self._chunker = chunker
        self._retriever = retriever
        self._repository = repository
        self._url_loader = url_loader
        self._clock = clock if clock is not None else _utc_now

    def index(self, paths: Iterable[Path], force: bool = False) -> IndexingReport:
        """Indexes ``paths``; files whose content is already indexed are skipped
        unless ``force`` is set."""
        run = _IndexingRun({} if force else self._known_hashes())
        for path in paths:
            try:
                document = self._load(path)
            except UnsupportedFileError:
                logger.debug("skipped unsupported file", extra={"path": str(path)})
                run.skipped.append(str(path))
                continue
            self._store(document, run)
        return self._finish(run)

    def index_urls(self, urls: Iterable[str], force: bool = False) -> IndexingReport:
        """Fetches and indexes web pages; pages whose content is already indexed are
        skipped unless ``force`` is set. A page that cannot be fetched or read is
        reported in ``failed`` and the others are still indexed."""
        run = _IndexingRun({} if force else self._known_hashes())
        for url in urls:
            try:
                document = self._fetch(url)
            except (OSError, ValueError) as error:
                logger.warning("could not index page", extra={"url": url, "error": str(error)})
                run.failed.append((url, str(error) or type(error).__name__))
                continue
            self._store(document, run)
        return self._finish(run)

    def _store(self, document: Document, run: _IndexingRun) -> None:
        digest = content_hash(document)
        if run.known.get(document.source) == digest:
            logger.debug("skipped unchanged document", extra={"source": document.source})
            run.unchanged += 1
            return
        indexed_at = self._clock().isoformat(timespec="seconds")
        new_chunks = [
            replace(chunk, content_hash=digest, indexed_at=indexed_at)
            for chunk in self._chunker.split(document)
        ]
        self._retriever.remove(document.source)
        self._retriever.add(new_chunks)
        logger.debug(
            "indexed document",
            extra={"source": document.source, "chunks": len(new_chunks)},
        )
        run.documents += 1
        run.chunks += len(new_chunks)

    def _finish(self, run: _IndexingRun) -> IndexingReport:
        if run.documents:
            self._repository.save(self._retriever)
        logger.info(
            "indexing finished",
            extra={
                "documents": run.documents,
                "chunks": run.chunks,
                "unchanged": run.unchanged,
                "skipped": len(run.skipped),
                "failed": len(run.failed),
            },
        )
        return IndexingReport(
            run.documents, run.chunks, tuple(run.skipped), run.unchanged, tuple(run.failed)
        )

    def _known_hashes(self) -> dict[str, str]:
        return {chunk.source: chunk.content_hash for chunk in self._retriever.chunks()}

    def _load(self, path: Path) -> Document:
        for loader in self._loaders:
            if loader.supports(path):
                return loader.load(path)
        raise UnsupportedFileError(f"No loader for {path.suffix or path.name}")

    def _fetch(self, url: str) -> Document:
        if self._url_loader is None:
            raise ValueError("Indexing web pages is not configured")
        return self._url_loader.load(url)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class _IndexingRun:
    """Counts what one ``index`` or ``index_urls`` call did."""

    known: dict[str, str]
    documents: int = 0
    chunks: int = 0
    unchanged: int = 0
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class RemovalReport:
    documents: tuple[str, ...]
    chunks: int


class RemovalService:
    """Drops a file, every file under a folder, or web pages from the index."""

    def __init__(self, retriever: Retriever, repository: IndexRepository) -> None:
        self._retriever = retriever
        self._repository = repository

    def remove(self, path: Path) -> RemovalReport:
        matched = tuple(
            source
            for source in self._sources()
            if not is_url(source) and _is_within(Path(source), path)
        )
        return self._drop(str(path), matched)

    def remove_url(self, url: str) -> RemovalReport:
        """Drops the page at ``url`` and every indexed page below it
        (``https://example.com/docs`` also drops ``https://example.com/docs/setup``)."""
        prefix = url.rstrip("/") + "/"
        matched = tuple(
            source
            for source in self._sources()
            if is_url(source) and (source == url or source.startswith(prefix))
        )
        return self._drop(url, matched)

    def _sources(self) -> list[str]:
        return sorted({chunk.source for chunk in self._retriever.chunks()})

    def _drop(self, target: str, matched: tuple[str, ...]) -> RemovalReport:
        chunks = sum(self._retriever.remove(source) for source in matched)
        logger.info(
            "removal finished",
            extra={"path": target, "documents": len(matched), "chunks": chunks},
        )
        if matched:
            self._repository.save(self._retriever)
        return RemovalReport(matched, chunks)


@dataclass(frozen=True)
class WatchUpdate:
    """What one batch of file changes did to the index."""

    changes: FileChanges
    indexing: IndexingReport
    removed: tuple[str, ...] = ()
    """Sources dropped because their file was deleted."""
    removed_chunks: int = 0

    def __bool__(self) -> bool:
        """True when the index changed."""
        return bool(self.indexing.documents or self.removed)


class WatchService:
    """Keeps the index in sync with folders: re-indexes changed files, drops deleted ones.

    ``indexing`` and ``removal`` must share one retriever, or each would save over the
    other's changes.
    """

    def __init__(
        self, indexing: IndexingService, removal: RemovalService, watcher: FileWatcher
    ) -> None:
        self._indexing = indexing
        self._removal = removal
        self._watcher = watcher

    def watch(self, roots: Sequence[Path]) -> Iterator[WatchUpdate]:
        """Yields one update per batch of changes, forever (the first one covers the files
        already there; unchanged ones are skipped by their content hash)."""
        for changes in self._watcher.watch(roots):
            yield self.apply(changes)

    def apply(self, changes: FileChanges) -> WatchUpdate:
        indexing = self._indexing.index(changes.changed)
        removed: list[str] = []
        chunks = 0
        for path in changes.removed:
            report = self._removal.remove(path)
            removed.extend(report.documents)
            chunks += report.chunks
        logger.info(
            "applied file changes",
            extra={
                "changed": len(changes.changed),
                "deleted": len(changes.removed),
                "indexed": indexing.documents,
                "removed": len(removed),
            },
        )
        return WatchUpdate(changes, indexing, tuple(removed), chunks)


class LiveWatchService:
    """Keeps the index in sync with folders while something else also writes to it.

    ``WatchService`` holds one retriever for as long as it watches, so index changes made
    elsewhere meanwhile (an MCP tool indexing a file, say) would be saved over by its next
    batch. Here every batch is applied by a fresh ``WatchService`` from ``appliers``,
    built from the index as it is on disk at that moment, inside ``guard`` (e.g. a lock
    the other writers hold too).
    """

    def __init__(
        self,
        watcher: FileWatcher,
        appliers: Callable[[], WatchService],
        guard: AbstractContextManager[object] | None = None,
    ) -> None:
        self._watcher = watcher
        self._appliers = appliers
        self._guard = guard if guard is not None else nullcontext()

    def watch(self, roots: Sequence[Path]) -> Iterator[WatchUpdate]:
        """Yields one update per batch of changes, forever (see ``WatchService.watch``)."""
        for changes in self._watcher.watch(roots):
            with self._guard:
                update = self._appliers().apply(changes)
            yield update


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


@dataclass(frozen=True)
class SearchReport:
    query: str
    results: tuple[SearchResult, ...]
    content: str
    """The rendered results page, e.g. a complete HTML document."""


class SearchReportService:
    """Searches the index and renders the ranked passages as a results page."""

    def __init__(self, searching: SearchService, renderer: SearchRenderer) -> None:
        self._searching = searching
        self._renderer = renderer

    def report(self, query: str, top_k: int = 5) -> str:
        """The rendered page; a blank query renders the page without searching."""
        return self.search(query, top_k).content

    def search(self, query: str, top_k: int = 5) -> SearchReport:
        """The ranked results together with their rendered page, for callers that need both."""
        query = query.strip()
        results = tuple(self._searching.search(query, top_k)) if query else ()
        content = self._renderer.render(query, results)
        logger.debug("rendered search report", extra={"characters": len(content)})
        return SearchReport(query, results, content)


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
        cost_estimator: CostEstimator | None = None,
    ) -> None:
        """``cost_estimator`` prices the tokens of each answer when the generator reports
        them; without one, answers still carry their token usage but no cost."""
        self._retriever = retriever
        self._generator = generator
        self._highlighter = highlighter
        self._cost_estimator = cost_estimator

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
        return _with_usage(
            Answer(question, text, tuple(results)), self._generator, self._cost_estimator
        )

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


def _with_usage(
    answer: Answer, generator: object, cost_estimator: CostEstimator | None
) -> Answer:
    """``answer`` with the tokens the generator just spent on it and their estimated cost."""
    if not isinstance(generator, UsageReportingGenerator) or generator.last_usage is None:
        return answer
    usage = generator.last_usage
    cost = cost_estimator.estimate(usage) if cost_estimator else None
    logger.debug(
        "answer usage",
        extra={
            "model": usage.model,
            "input_tokens": usage.total_input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": cost,
        },
    )
    return replace(answer, usage=usage, cost_usd=cost)


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
        cost_estimator: CostEstimator | None = None,
    ) -> None:
        if max_turns < 0:
            raise ValueError("max_turns must not be negative")
        self._retriever = retriever
        self._generator = generator
        self._highlighter = highlighter
        self._max_turns = max_turns
        self._cost_estimator = cost_estimator
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
        return _with_usage(
            Answer(question, text, tuple(results)), self._generator, self._cost_estimator
        )


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
    """Lower-case extension without the dot, e.g. ``md``; ``other`` when there is none
    and ``web`` for pages indexed by URL."""
    if is_url(source):
        return "web"
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
