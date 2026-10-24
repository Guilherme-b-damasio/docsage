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
    RemovalReport,
)
from docsage.domain.models import (
    Answer,
    CaseOutcome,
    Chunk,
    EvaluationReport,
    Highlight,
    IndexOverview,
    IndexStats,
    SearchResult,
    TermScore,
    TokenUsage,
)


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


def term_score_to_dict(contribution: TermScore) -> dict[str, Any]:
    return {"term": contribution.term, "score": round(contribution.score, 4)}


def search_result_to_dict(result: SearchResult, rank: int) -> dict[str, Any]:
    return {
        "rank": rank,
        "score": round(result.score, 4),
        "matched_terms": list(result.matched_terms),
        "highlights": [highlight_to_dict(item) for item in result.highlights],
        "contributions": [term_score_to_dict(item) for item in result.contributions],
        "chunk": chunk_to_dict(result.chunk),
    }


def search_results_to_dict(
    query: str, results: Sequence[SearchResult], source: str = ""
) -> dict[str, Any]:
    """``source`` is the filter the search ran with, empty when every source was searched."""
    return {
        "query": query,
        "source": source,
        "results": [
            search_result_to_dict(result, rank) for rank, result in enumerate(results, start=1)
        ],
    }


def usage_to_dict(usage: TokenUsage) -> dict[str, Any]:
    return {
        "model": usage.model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_creation_input_tokens": usage.cache_creation_input_tokens,
        "cache_read_input_tokens": usage.cache_read_input_tokens,
    }


def answer_to_dict(answer: Answer) -> dict[str, Any]:
    return {
        "question": answer.question,
        "answer": answer.text,
        "sources": [
            search_result_to_dict(result, rank)
            for rank, result in enumerate(answer.sources, start=1)
        ],
        "source": answer.source,
        "usage": usage_to_dict(answer.usage) if answer.usage else None,
        "cost_usd": round(answer.cost_usd, 6) if answer.cost_usd is not None else None,
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


def overview_to_dict(overview: IndexOverview) -> dict[str, Any]:
    return {
        "documents": overview.documents,
        "chunks": overview.chunks,
        "terms": overview.terms,
        "vocabulary": overview.vocabulary,
        "index_bytes": overview.index_bytes,
        "documents_by_type": [
            {"type": name, "documents": count} for name, count in overview.documents_by_type
        ],
        "chunk_lengths": [
            {"low": item.low, "high": item.high, "chunks": item.count}
            for item in overview.chunk_lengths
        ],
        "top_terms": [{"term": term, "count": count} for term, count in overview.top_terms],
        "relations": [
            {
                "first": item.first,
                "second": item.second,
                "shared_terms": list(item.shared_terms),
            }
            for item in overview.relations
        ],
        "chunk_map": [
            {"chunk_id": point.chunk_id, "source": point.source, "x": point.x, "y": point.y}
            for point in overview.chunk_map
        ],
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
        "failed": [{"url": url, "reason": reason} for url, reason in report.failed],
    }


def removal_report_to_dict(path: str, report: RemovalReport) -> dict[str, Any]:
    return {"path": path, "documents": list(report.documents), "chunks": report.chunks}


def dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2)


def case_outcome_to_dict(outcome: CaseOutcome) -> dict[str, Any]:
    return {
        "query": outcome.case.query,
        "relevant": list(outcome.case.relevant),
        "first_hit": outcome.first_hit,
        "recall": round(outcome.recall, 4),
        "reciprocal_rank": round(outcome.reciprocal_rank, 4),
        "retrieved": list(outcome.ranked_sources),
    }


def evaluation_to_dict(report: EvaluationReport) -> dict[str, Any]:
    return {
        "k": report.k,
        "queries": len(report.outcomes),
        "recall": round(report.recall, 4),
        "mrr": round(report.mrr, 4),
        "recall_curve": [round(value, 4) for value in report.recall_curve],
        "cases": [case_outcome_to_dict(outcome) for outcome in report.outcomes],
    }
