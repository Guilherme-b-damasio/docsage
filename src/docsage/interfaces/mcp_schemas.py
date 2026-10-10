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


class RankedChunkOutput(TypedDict):
    rank: int
    score: float
    matched_terms: list[str]
    highlights: list[HighlightOutput]
    """Character offsets into ``chunk.text`` where each query term occurs."""
    chunk: ChunkOutput


class SearchOutput(TypedDict):
    query: str
    results: list[RankedChunkOutput]


class AnswerOutput(TypedDict):
    question: str
    answer: str
    sources: list[RankedChunkOutput]


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
