"""Renders the index overview as a self-contained HTML dashboard."""

from __future__ import annotations

from html import escape

from docsage.domain.models import HistogramBin, IndexOverview
from docsage.infrastructure.html_page import page
from docsage.infrastructure.svg_charts import CHART_CSS, bar_chart, column_chart, data_table
from docsage.infrastructure.units import human_size

DASHBOARD_CSS = """
.tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }
.tiles { margin-bottom: 12px; }
.tile { margin: 0; }
.card > h2:first-child { margin-top: 0; }
.tile .number { font-size: 1.8rem; font-weight: 600; font-variant-numeric: tabular-nums; }
.tile .caption { color: var(--muted); font-size: 0.9rem; }
"""


class HtmlDashboardRenderer:
    """Stat tiles plus three inline-SVG charts: documents per file type, chunk lengths
    and top terms. Every chart has a hover tooltip and a table view underneath."""

    def render(self, overview: IndexOverview) -> str:
        body = [
            '<header>\n<h1>docsage index</h1>\n<p class="muted">'
            f"{overview.documents:,} documents, {overview.chunks:,} chunks</p>\n</header>",
            self._tiles(overview),
        ]
        if overview.chunks:
            body += [
                self._section(
                    "Documents per file type",
                    bar_chart(overview.documents_by_type, "Documents per file type"),
                    ("File type", "Documents"),
                    overview.documents_by_type,
                ),
                self._section(
                    "Chunk length (words)",
                    column_chart(_bins(overview.chunk_lengths), "Chunks per length range"),
                    ("Words", "Chunks"),
                    _bins(overview.chunk_lengths),
                ),
                self._section(
                    "Top terms",
                    bar_chart(overview.top_terms, "Most frequent terms"),
                    ("Term", "Occurrences"),
                    overview.top_terms,
                ),
            ]
        else:
            body.append('<p class="card">The index is empty. Run <code>docsage index</code>.</p>')
        return page("docsage index", "\n".join(body), CHART_CSS + DASHBOARD_CSS)

    @staticmethod
    def _tiles(overview: IndexOverview) -> str:
        tiles = [
            (f"{overview.documents:,}", "documents"),
            (f"{overview.chunks:,}", "chunks"),
            (f"{overview.vocabulary:,}", f"distinct terms of {overview.terms:,}"),
            (human_size(overview.index_bytes), "index size"),
        ]
        cells = "".join(
            f'<div class="card tile"><div class="number">{escape(number)}</div>'
            f'<div class="caption">{escape(caption)}</div></div>'
            for number, caption in tiles
        )
        return f'<section class="tiles" aria-label="Summary">{cells}</section>'

    @staticmethod
    def _section(
        title: str, chart: str, headers: tuple[str, str], rows: tuple[tuple[str, int], ...]
    ) -> str:
        return (
            f'<section class="card">\n<h2>{escape(title)}</h2>\n{chart}\n'
            f"{data_table(headers, rows)}\n</section>"
        )


def _bins(bins: tuple[HistogramBin, ...]) -> tuple[tuple[str, int], ...]:
    return tuple(
        (str(item.low) if item.low == item.high else f"{item.low}–{item.high}", item.count)
        for item in bins
    )
