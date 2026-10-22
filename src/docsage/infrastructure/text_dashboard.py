"""Plain-text fallback for the index dashboard, with bars drawn in block characters."""

from __future__ import annotations

from collections.abc import Sequence

from docsage.domain.models import ChunkPoint, IndexOverview
from docsage.infrastructure.mermaid import document_labels
from docsage.infrastructure.units import human_size, indexed_label

BAR_WIDTH = 30
MAP_WIDTH = 48
MAP_HEIGHT = 14


class TextDashboardRenderer:
    """The dashboard's numbers and charts for terminals and text-only clients."""

    def render(self, overview: IndexOverview) -> str:
        lines = [
            f"Documents:  {overview.documents:,}",
            f"Chunks:     {overview.chunks:,}",
            f"Terms:      {overview.terms:,} ({overview.vocabulary:,} distinct)",
            f"Index size: {human_size(overview.index_bytes)}",
        ]
        sections = [
            ("Documents per file type", overview.documents_by_type),
            (
                "Chunk length (words)",
                tuple((_range(item.low, item.high), item.count) for item in overview.chunk_lengths),
            ),
            ("Top terms", overview.top_terms),
        ]
        for title, rows in sections:
            if rows:
                lines += ["", f"{title}:", *bars(rows)]
        if overview.recent_documents:
            lines += ["", "Recently indexed:", *recent_lines(overview)]
        if overview.relations:
            lines += ["", "Related documents (shared top terms):", *relation_lines(overview)]
        if overview.chunk_map:
            lines += ["", "Chunk map (PCA of embeddings):", *map_lines(overview.chunk_map)]
        return "\n".join(lines) + "\n"


def bars(rows: Sequence[tuple[str, int]], width: int = BAR_WIDTH) -> list[str]:
    """One ``name  ████ value`` line per row, scaled so the largest value fills ``width``."""
    peak = max(value for _, value in rows) or 1
    names = max(len(name) for name, _ in rows)
    return [
        f"  {name:<{names}}  {'█' * round(width * value / peak)} {value:,}".rstrip()
        for name, value in rows
    ]


def recent_lines(overview: IndexOverview) -> list[str]:
    """One ``2026-10-22 09:30 UTC  notes.md (3 chunks)`` line per document, newest first."""
    return [
        f"  {indexed_label(item.indexed_at):<20}  {item.source} "
        f"({item.chunks:,} chunk{'' if item.chunks == 1 else 's'})"
        for item in overview.recent_documents
    ]


def relation_lines(overview: IndexOverview) -> list[str]:
    """One ``a.md <-> b.md: shared, terms`` line per related pair."""
    relations = overview.relations
    sources = {item.first for item in relations} | {item.second for item in relations}
    labels = document_labels(sorted(sources))
    return [
        f"  {labels[item.first]} <-> {labels[item.second]}: {', '.join(item.shared_terms)}"
        for item in relations
    ]


MAP_SYMBOLS = "abcdefghijklmnopqrstuvwxyz"
"""One letter per document; documents beyond the alphabet share ``+``."""


def map_lines(
    points: Sequence[ChunkPoint], width: int = MAP_WIDTH, height: int = MAP_HEIGHT
) -> list[str]:
    """Chunks as letters on a framed grid, followed by a letter-to-document key.

    A cell where chunks of different documents meet shows ``*``.
    """
    sources = sorted({point.source for point in points})
    labels = document_labels(sources)
    symbols = {
        source: MAP_SYMBOLS[index] if index < len(MAP_SYMBOLS) else "+"
        for index, source in enumerate(sources)
    }
    grid = [[" "] * width for _ in range(height)]
    for point in points:
        column = min(width - 1, round((point.x + 1) / 2 * (width - 1)))
        row = min(height - 1, round((1 - point.y) / 2 * (height - 1)))
        cell = grid[row][column]
        symbol = symbols[point.source]
        grid[row][column] = symbol if cell in (" ", symbol) else "*"
    border = "  +" + "-" * width + "+"
    lines = [border, *(f"  |{''.join(row)}|" for row in grid), border]
    lines += [f"  {symbols[source]} = {labels[source]}" for source in sources[: len(MAP_SYMBOLS)]]
    if len(sources) > len(MAP_SYMBOLS):
        lines.append(f"  + = {len(sources) - len(MAP_SYMBOLS)} other documents")
    return lines


def _range(low: int, high: int) -> str:
    return str(low) if low == high else f"{low}-{high}"
