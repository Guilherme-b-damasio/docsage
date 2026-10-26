"""Core domain entities. Pure data, no I/O and no third-party dependencies."""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path

WEB_SCHEMES = ("http://", "https://")


def is_url(source: str) -> bool:
    """True for a web page address, which is indexed by URL instead of by path."""
    return source.lower().startswith(WEB_SCHEMES)


@dataclass(frozen=True)
class Document:
    """A source document loaded from disk or fetched from the web."""

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
    section: str = ""
    """Heading path the chunk belongs to, e.g. ``Setup > Install`` (Markdown only)."""
    indexed_at: str = ""
    """When the source document was indexed, as an ISO 8601 UTC timestamp (empty for
    chunks indexed before docsage recorded it)."""

    @property
    def citation(self) -> str:
        """Human-readable location, e.g. ``guide.pdf, p. 3`` or ``notes.md, Setup > Install``."""
        if self.section:
            return f"{self.source}, {self.section}"
        if self.first_page is None:
            return self.source
        if self.last_page is None or self.last_page == self.first_page:
            return f"{self.source}, p. {self.first_page}"
        return f"{self.source}, pp. {self.first_page}-{self.last_page}"


@dataclass(frozen=True)
class Highlight:
    """A span of a chunk's text that matched a query term."""

    start: int
    """Character offset where the match starts in ``Chunk.text``."""
    end: int
    """Character offset just past the match, so ``text[start:end]`` is the matched word."""
    term: str
    """Normalized query term the span matched, e.g. ``index`` for ``Index``."""


@dataclass(frozen=True)
class SourceView:
    """An indexed source's whole text with one cited passage marked inside it.

    A viewer shows ``text`` as it was indexed and marks ``text[passage_start:passage_end]``
    as the cited passage, with ``highlights`` pointing at the query terms found in it, so
    the reader sees the passage in its surrounding document.
    """

    source: str
    text: str
    passage_start: int | None = None
    """Where the cited passage begins in ``text`` (None when no passage is marked)."""
    passage_end: int | None = None
    """Offset just past the cited passage, so ``text[start:end]`` is the passage."""
    highlights: tuple[Highlight, ...] = ()
    """Matched terms inside the passage, as offsets in ``text`` (not in the passage)."""

    @property
    def passage(self) -> str:
        """The cited passage, or an empty string when none is marked."""
        if self.passage_start is None or self.passage_end is None:
            return ""
        return self.text[self.passage_start : self.passage_end]

    def __post_init__(self) -> None:
        if (self.passage_start is None) != (self.passage_end is None):
            raise ValueError("A marked passage needs both passage_start and passage_end")
        if self.passage_start is not None and self.passage_end is not None:
            if not 0 <= self.passage_start <= self.passage_end <= len(self.text):
                raise ValueError("The marked passage must lie inside the source's text")


@dataclass(frozen=True)
class SourceFilter:
    """Which indexed sources a search may return; an empty pattern keeps every source.

    A pattern is read as one of three things, in this order:

    * a file type, when it starts with a dot or ``*.``: ``.md``, ``*.pdf``;
    * a web address prefix, when it starts with ``http://`` or ``https://``;
    * a path, otherwise: it matches a source whose folders (or whole path) contain the
      pattern's segments in order, so ``docs`` matches ``project/docs/faq.md`` and
      ``docs/api`` only matches below that folder.

    Matching ignores case and reads a Windows separator as ``/``, so a pattern written
    either way matches sources indexed on Windows and on POSIX alike.
    """

    pattern: str = ""

    def __bool__(self) -> bool:
        """False when the filter keeps every source, so callers can skip the work."""
        return bool(self._wanted)

    def matches(self, source: str) -> bool:
        wanted = self._wanted
        if not wanted:
            return True
        found = _normalized(source)
        if wanted.startswith("."):
            return found.endswith(wanted)
        if is_url(wanted):
            return found.startswith(wanted)
        return _contains_segments(found, wanted)

    @property
    def _wanted(self) -> str:
        """The pattern as it is matched: normalized, without a leading ``*``."""
        return _normalized(self.pattern).lstrip("*")


def _normalized(value: str) -> str:
    return value.strip().replace("\\", "/").casefold()


def _contains_segments(source: str, wanted: str) -> bool:
    """True when ``wanted``'s path segments appear in a row in ``source``, at a boundary."""
    found = [segment for segment in source.split("/") if segment]
    segments = [segment for segment in wanted.split("/") if segment]
    if not segments or len(segments) > len(found):
        return False
    return any(
        found[start : start + len(segments)] == segments
        for start in range(len(found) - len(segments) + 1)
    )


@dataclass(frozen=True)
class TermScore:
    """How much one query term added to a result's relevance score."""

    term: str
    score: float


@dataclass(frozen=True)
class SearchResult:
    """A chunk paired with its relevance score for a query."""

    chunk: Chunk
    score: float
    highlights: tuple[Highlight, ...] = ()
    """Where the query terms occur in the chunk, in text order (empty if not computed)."""
    contributions: tuple[TermScore, ...] = ()
    """Per-term share of ``score``, largest first (empty when the retriever cannot tell)."""

    @property
    def matched_terms(self) -> tuple[str, ...]:
        """Distinct query terms found in the chunk, in order of first occurrence."""
        return tuple(dict.fromkeys(highlight.term for highlight in self.highlights))


@dataclass(frozen=True)
class TokenUsage:
    """Tokens one generated answer consumed, as the model provider counted them."""

    model: str
    """Model that actually wrote the answer (a fallback model when the first one declined)."""
    input_tokens: int
    """Uncached input tokens, billed at the full input price."""
    output_tokens: int
    cache_creation_input_tokens: int = 0
    """Input tokens written to the prompt cache, billed slightly above the input price."""
    cache_read_input_tokens: int = 0
    """Input tokens served from the prompt cache, billed at a fraction of the input price."""

    @property
    def total_input_tokens(self) -> int:
        return self.input_tokens + self.cache_creation_input_tokens + self.cache_read_input_tokens


@dataclass(frozen=True)
class Answer:
    """A generated answer and the chunks it was grounded on."""

    question: str
    text: str
    sources: tuple[SearchResult, ...]
    usage: TokenUsage | None = None
    """Tokens spent on the answer (None when no model was called or it did not report them)."""
    cost_usd: float | None = None
    """Estimated price of ``usage`` in US dollars (None when the model's price is unknown)."""
    source: str = ""
    """The ``SourceFilter`` pattern the passages were retrieved under; empty when the whole
    index was searched."""

    def cited_documents(self) -> tuple[CitedDocument, ...]:
        """The cited passages grouped by the document they come from, newest first.

        A report reads better document by document than passage by passage, and the
        document indexed most recently leads, so the freshest material is on top;
        documents whose index time is unknown come last, and documents indexed together
        keep the order their best passage was ranked in. Each passage keeps the rank it
        was cited with, so the ``[n]`` markers in the answer's text still match.
        """
        groups: dict[str, list[Citation]] = {}
        for rank, result in enumerate(self.sources, start=1):
            groups.setdefault(result.chunk.source, []).append(Citation(rank, result))
        documents = [
            CitedDocument(source, _newest(citations), tuple(citations))
            for source, citations in groups.items()
        ]
        documents.sort(key=lambda document: document.best_rank)
        # Stable, so documents indexed at the same time stay in best-rank order, and an
        # unknown time sorts below every real one.
        documents.sort(key=lambda document: document.indexed_at, reverse=True)
        return tuple(documents)


def _newest(citations: list[Citation]) -> str:
    """The most recent ``indexed_at`` among ``citations``, empty when none records one."""
    return max(citation.result.chunk.indexed_at for citation in citations)


@dataclass(frozen=True)
class Citation:
    """One cited passage and the number it was cited with in the answer's text."""

    rank: int
    result: SearchResult


@dataclass(frozen=True)
class CitedDocument:
    """Every passage an answer cited from one document, in the order they were cited."""

    source: str
    indexed_at: str
    """When the document was indexed, as an ISO 8601 UTC timestamp (empty when unknown)."""
    citations: tuple[Citation, ...]

    @property
    def best_rank(self) -> int:
        """The lowest rank the document was cited with, i.e. its best passage."""
        return min(citation.rank for citation in self.citations)


@dataclass(frozen=True)
class ComparedAnswer:
    """One side of a comparison: an answer and the settings that produced it."""

    label: str
    """The retrieval settings in a few words, e.g. ``bm25, top 5``."""
    answer: Answer


@dataclass(frozen=True)
class AnswerComparison:
    """The same question answered twice under different retrieval settings."""

    left: ComparedAnswer
    right: ComparedAnswer

    @property
    def question(self) -> str:
        return self.left.answer.question

    def shared_chunks(self) -> frozenset[str]:
        """Ids of the passages both answers were grounded on."""
        return _chunk_ids(self.left.answer) & _chunk_ids(self.right.answer)

    def overlap(self) -> float:
        """Shared passages over all distinct passages (Jaccard), 1.0 when neither side
        retrieved anything, so two empty answers count as the same."""
        either = _chunk_ids(self.left.answer) | _chunk_ids(self.right.answer)
        if not either:
            return 1.0
        return len(self.shared_chunks()) / len(either)


def _chunk_ids(answer: Answer) -> frozenset[str]:
    return frozenset(result.chunk.id for result in answer.sources)


ANSWER_LENGTHS = ("short", "medium", "long")
"""How long generated answers should be; ``medium`` leaves it to the model."""


@dataclass(frozen=True)
class AnswerStyle:
    """How generated answers should read, whatever the question."""

    language: str = ""
    """Language to answer in, e.g. ``Portuguese``; empty means the language of the question."""
    length: str = "medium"
    """One of ``ANSWER_LENGTHS``."""

    def __post_init__(self) -> None:
        if self.length not in ANSWER_LENGTHS:
            raise ValueError(
                f"Unknown answer length: {self.length} (choose from {', '.join(ANSWER_LENGTHS)})"
            )


@dataclass(frozen=True)
class ChatTurn:
    """One finished exchange of a conversation: what was asked and what was answered."""

    question: str
    answer: str


@dataclass(frozen=True)
class HistogramBin:
    """Values ``low <= value <= high`` and how many fell in that range."""

    low: int
    high: int
    count: int


@dataclass(frozen=True)
class DocumentRelation:
    """Two documents linked by the characteristic terms they have in common."""

    first: str
    second: str
    shared_terms: tuple[str, ...]
    """Terms among the top terms of both documents, most characteristic first."""

    @property
    def strength(self) -> int:
        return len(self.shared_terms)


@dataclass(frozen=True)
class ChunkPoint:
    """A chunk placed on a 2D map where nearby points have similar meaning."""

    chunk_id: str
    source: str
    x: float
    y: float
    """Coordinates scaled to ``-1..1`` on each axis."""


@dataclass(frozen=True)
class RecentDocument:
    """A document of the index, when it was indexed and into how many chunks."""

    source: str
    indexed_at: str
    """ISO 8601 UTC timestamp, empty when the index does not record it."""
    chunks: int


@dataclass(frozen=True)
class IndexStats:
    """Headline numbers of the index and its most frequent terms."""

    documents: int
    chunks: int
    terms: int
    """Indexed terms summed over chunks (overlapping windows count twice)."""
    vocabulary: int
    top_terms: tuple[tuple[str, int], ...]
    index_bytes: int


@dataclass(frozen=True)
class IndexOverview:
    """Everything the index dashboard shows, computed once from the stored chunks."""

    documents: int
    chunks: int
    terms: int
    vocabulary: int
    index_bytes: int
    documents_by_type: tuple[tuple[str, int], ...]
    """``(file type, documents)`` pairs, most common type first."""
    chunk_lengths: tuple[HistogramBin, ...]
    """Distribution of chunk lengths in words, in ascending ranges."""
    top_terms: tuple[tuple[str, int], ...]
    relations: tuple[DocumentRelation, ...] = ()
    """Pairs of documents sharing top terms, strongest first."""
    chunk_map: tuple[ChunkPoint, ...] = ()
    """Every chunk on a 2D map of its embedding (empty without an embedding model)."""
    recent_documents: tuple[RecentDocument, ...] = ()
    """The most recently indexed documents, newest first."""


@dataclass(frozen=True)
class EvaluationCase:
    """A labeled query: the documents a good retriever should return for it."""

    query: str
    relevant: tuple[str, ...]
    """Sources that answer the query, as full paths or path suffixes like ``docs/faq.md``."""


@dataclass(frozen=True)
class CaseOutcome:
    """How the retriever did on one labeled query."""

    case: EvaluationCase
    ranked_sources: tuple[str, ...]
    """Source of each retrieved chunk, best first (sources repeat across chunks)."""
    first_hit: int | None
    """1-based rank of the first chunk from a relevant source, None when none was retrieved."""
    recall_curve: tuple[float, ...]
    """Share of the relevant sources found within the top 1, 2, ... k chunks."""

    @property
    def recall(self) -> float:
        """Recall at the evaluation's cut-off ``k``."""
        return self.recall_curve[-1] if self.recall_curve else 0.0

    @property
    def reciprocal_rank(self) -> float:
        return 1 / self.first_hit if self.first_hit else 0.0


@dataclass(frozen=True)
class EvaluationReport:
    """Retrieval quality over a labeled query set: recall@k and mean reciprocal rank."""

    k: int
    outcomes: tuple[CaseOutcome, ...]

    @property
    def recall_curve(self) -> tuple[float, ...]:
        """Mean recall@1, recall@2, ... recall@k over every query."""
        if not self.outcomes:
            return ()
        return tuple(
            sum(outcome.recall_curve[cut] for outcome in self.outcomes) / len(self.outcomes)
            for cut in range(self.k)
        )

    @property
    def recall(self) -> float:
        """Mean recall@k."""
        return self.recall_curve[-1] if self.outcomes else 0.0

    @property
    def mrr(self) -> float:
        """Mean reciprocal rank of the first relevant chunk (0 for queries that miss)."""
        if not self.outcomes:
            return 0.0
        return sum(outcome.reciprocal_rank for outcome in self.outcomes) / len(self.outcomes)


@dataclass(frozen=True)
class FileChanges:
    """Files that appeared, changed or disappeared under watched folders since the last look."""

    changed: tuple[Path, ...] = ()
    """Files created or modified, in sorted order."""
    removed: tuple[Path, ...] = ()
    """Files deleted, in sorted order."""

    def __bool__(self) -> bool:
        return bool(self.changed or self.removed)
