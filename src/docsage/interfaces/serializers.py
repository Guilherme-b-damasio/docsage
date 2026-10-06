"""Turns domain objects into JSON-ready dicts.

Shared by every interface (CLI ``--json`` today, the MCP server later) so they all
expose the same shape.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from docsage.application.services import IndexStats
from docsage.domain.models import Answer, Chunk, SearchResult


def chunk_to_dict(chunk: Chunk) -> dict[str, Any]:
    return {
        "id": chunk.id,
        "source": chunk.source,
        "position": chunk.position,
        "text": chunk.text,
    }


def search_result_to_dict(result: SearchResult, rank: int) -> dict[str, Any]:
    return {"rank": rank, "score": round(result.score, 4), "chunk": chunk_to_dict(result.chunk)}


def search_results_to_dict(query: str, results: Sequence[SearchResult]) -> dict[str, Any]:
    return {
        "query": query,
        "results": [
            search_result_to_dict(result, rank) for rank, result in enumerate(results, start=1)
        ],
    }


def answer_to_dict(answer: Answer) -> dict[str, Any]:
    return {
        "question": answer.question,
        "answer": answer.text,
        "sources": [
            search_result_to_dict(result, rank)
            for rank, result in enumerate(answer.sources, start=1)
        ],
    }


def stats_to_dict(stats: IndexStats) -> dict[str, Any]:
    return {
        "documents": stats.documents,
        "chunks": stats.chunks,
        "terms": stats.terms,
        "vocabulary": stats.vocabulary,
        "top_terms": [{"term": term, "count": count} for term, count in stats.top_terms],
        "index_bytes": stats.index_bytes,
    }


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
