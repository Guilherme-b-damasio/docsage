"""Renders the index statistics as a self-contained HTML page: stat tiles and top terms."""

from __future__ import annotations

from docsage.domain.models import IndexStats
from docsage.infrastructure.html_dashboard import TILES_CSS, stat_tiles
from docsage.infrastructure.html_page import page
from docsage.infrastructure.svg_charts import CHART_CSS, bar_chart, data_table


class HtmlStatsRenderer:
    """The headline numbers as tiles, then the most frequent terms as an inline-SVG bar
    chart with a table view underneath. A lighter sibling of the full dashboard."""

    def render(self, stats: IndexStats) -> str:
        body = [
            '<header>\n<h1>docsage stats</h1>\n<p class="muted">'
            f"{stats.documents:,} documents, {stats.chunks:,} chunks</p>\n</header>",
            stat_tiles(
                stats.documents, stats.chunks, stats.terms, stats.vocabulary, stats.index_bytes
            ),
        ]
        if stats.top_terms:
            body.append(
                '<section class="card">\n<h2>Top terms</h2>\n'
                f"{bar_chart(stats.top_terms, 'Most frequent terms')}\n"
                f"{data_table(('Term', 'Occurrences'), stats.top_terms)}\n</section>"
            )
        elif not stats.chunks:
            body.append('<p class="card">The index is empty. Run <code>docsage index</code>.</p>')
        return page("docsage stats", "\n".join(body), CHART_CSS + TILES_CSS)
