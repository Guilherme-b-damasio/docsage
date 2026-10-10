"""Plain-text fallback for the index dashboard, with bars drawn in block characters."""

from __future__ import annotations

from collections.abc import Sequence

from docsage.domain.models import IndexOverview
from docsage.infrastructure.units import human_size

BAR_WIDTH = 30


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
        return "\n".join(lines) + "\n"


def bars(rows: Sequence[tuple[str, int]], width: int = BAR_WIDTH) -> list[str]:
    """One ``name  ████ value`` line per row, scaled so the largest value fills ``width``."""
    peak = max(value for _, value in rows) or 1
    names = max(len(name) for name, _ in rows)
    return [
        f"  {name:<{names}}  {'█' * round(width * value / peak)} {value:,}".rstrip()
        for name, value in rows
    ]


def _range(low: int, high: int) -> str:
    return str(low) if low == high else f"{low}-{high}"
