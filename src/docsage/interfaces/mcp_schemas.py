"""Output schemas of the MCP tools.

Each TypedDict mirrors a dict built by ``docsage.interfaces.serializers``; the server
publishes them as the tools' ``outputSchema`` and the SDK validates every result
against them, so a serializer that drifts from its schema fails loudly.
"""

from __future__ import annotations

# pydantic only accepts typing_extensions.TypedDict before Python 3.12.
from typing_extensions import TypedDict


class ChunkOutput(TypedDict):
    id: str
    source: str
    position: int
    first_page: int | None
    last_page: int | None
    section: str
    citation: str
    text: str


class HighlightOutput(TypedDict):
    start: int
    end: int
    term: str


class TermScoreOutput(TypedDict):
    term: str
    score: float


class RankedChunkOutput(TypedDict):
    rank: int
    score: float
    matched_terms: list[str]
    highlights: list[HighlightOutput]
    """Character offsets into ``chunk.text`` where each query term occurs."""
    contributions: list[TermScoreOutput]
    """How much each query term added to ``score`` (BM25), largest first."""
    chunk: ChunkOutput


class SearchOutput(TypedDict):
    query: str
    results: list[RankedChunkOutput]


class UsageOutput(TypedDict):
    model: str
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int


class AnswerOutput(TypedDict):
    question: str
    answer: str
    sources: list[RankedChunkOutput]
    usage: UsageOutput | None
    """Tokens Claude spent on the answer (null when no passages matched)."""
    cost_usd: float | None
    """Estimated price of ``usage`` in US dollars (null when the model's price is unknown)."""


class IndexingOutput(TypedDict):
    documents: int
    chunks: int
    unchanged: int
    skipped: list[str]


class RemovalOutput(TypedDict):
    path: str
    documents: list[str]
    chunks: int


class TermCountOutput(TypedDict):
    term: str
    count: int


class StatsOutput(TypedDict):
    documents: int
    chunks: int
    terms: int
    vocabulary: int
    top_terms: list[TermCountOutput]
    index_bytes: int


class FileTypeCountOutput(TypedDict):
    type: str
    documents: int


class LengthBinOutput(TypedDict):
    low: int
    high: int
    """Inclusive bounds of the range, in words."""
    chunks: int


class RelationOutput(TypedDict):
    first: str
    second: str
    shared_terms: list[str]
    """Characteristic terms both documents share, most characteristic first."""


class ChunkPointOutput(TypedDict):
    chunk_id: str
    source: str
    x: float
    y: float
    """Position on the 2D map of chunk embeddings, each axis scaled to -1..1."""


class DashboardOutput(TypedDict):
    documents: int
    chunks: int
    terms: int
    vocabulary: int
    index_bytes: int
    documents_by_type: list[FileTypeCountOutput]
    chunk_lengths: list[LengthBinOutput]
    top_terms: list[TermCountOutput]
    relations: list[RelationOutput]
    chunk_map: list[ChunkPointOutput]
    """Empty unless the server runs with an embedding or hybrid retriever."""
