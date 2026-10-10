"""Turns domain objects into JSON-ready dicts.

Shared by every interface (CLI ``--json`` and the MCP server's structured tool output)
so they all expose the same shape.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from docsage.application.services import (
    DocumentSummary,
    IndexingReport,
    IndexStats,
    RemovalReport,
)
from docsage.domain.models import Answer, Chunk, Highlight, SearchResult


def chunk_to_dict(chunk: Chunk) -> dict[str, Any]:
    return {
        "id": chunk.id,
        "source": chunk.source,
        "position": chunk.position,
        "first_page": chunk.first_page,
        "last_page": chunk.last_page,
        "section": chunk.section,
        "citation": chunk.citation,
        "text": chunk.text,
    }


def highlight_to_dict(highlight: Highlight) -> dict[str, Any]:
    return {"start": highlight.start, "end": highlight.end, "term": highlight.term}


def search_result_to_dict(result: SearchResult, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "score": round(result.score, 4),
        "matched_terms": list(result.matched_terms),
        "highlights": [highlight_to_dict(item) for item in result.highlights],
        "chunk": chunk_to_dict(result.chunk),
    }


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


def document_summary_to_dict(summary: DocumentSummary) -> dict[str, Any]:
    return {
        "source": summary.source,
        "chunks": summary.chunks,
        "pages": summary.pages,
        "sections": list(summary.sections),
        "chunk_ids": list(summary.chunk_ids),
    }


def indexing_report_to_dict(report: IndexingReport) -> dict[str, Any]:
    return {
        "documents": report.documents,
        "chunks": report.chunks,
        "unchanged": report.unchanged,
        "skipped": list(report.skipped),
    }


def removal_report_to_dict(path: str, report: RemovalReport) -> dict[str, Any]:
    return {"path": path, "documents": list(report.documents), "chunks": report.chunks}


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)
