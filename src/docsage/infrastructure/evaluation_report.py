"""Renders a retrieval evaluation as a self-contained HTML page or as plain text."""

from __future__ import annotations

from html import escape

from docsage.domain.models import CaseOutcome, EvaluationReport
from docsage.infrastructure.html_dashboard import DASHBOARD_CSS
from docsage.infrastructure.html_page import page
from docsage.infrastructure.svg_charts import CHART_CSS, bar_chart, data_table, percent, text_table

BAR_WIDTH = 30


def _reciprocal(value: float) -> str:
    return f"{value:.2f}"


class HtmlEvaluationRenderer:
    """Stat tiles, recall at every cut-off and each query's reciprocal rank as inline-SVG
    bars, plus a table of every query with where its first relevant chunk ranked."""

    def render(self, report: EvaluationReport) -> str:
        title = "docsage retrieval evaluation"
        body = [
            f'<header>\n<h1>Retrieval evaluation</h1>\n<p class="muted">'
            f"{len(report.outcomes):,} labeled queries, top {report.k} chunks each</p>\n"
            "</header>",
            self._tiles(report),
        ]
        if report.outcomes:
            curve = recall_rows(report)
            ranks = [(_query_label(item), item.reciprocal_rank) for item in report.outcomes]
            body += [
                self._section(
                    "Recall by cut-off",
                    bar_chart(curve, "Mean recall at each cut-off", percent, full_scale=1.0)
                    + data_table(("Cut-off", "Recall"), curve, percent),
                ),
                self._section(
                    "Reciprocal rank per query",
                    bar_chart(ranks, "Reciprocal rank per query", _reciprocal, full_scale=1.0)
                    + data_table(("Query", "Reciprocal rank"), ranks, _reciprocal),
                ),
                self._section("Queries", self._queries(report)),
            ]
        return page(title, "\n".join(body), CHART_CSS + DASHBOARD_CSS)

    @staticmethod
    def _tiles(report: EvaluationReport) -> str:
        misses = sum(1 for outcome in report.outcomes if outcome.first_hit is None)
        tiles = [
            (f"{report.recall:.0%}", f"recall@{report.k}"),
            (f"{report.mrr:.2f}", "mean reciprocal rank"),
            (f"{len(report.outcomes):,}", "queries"),
            (f"{misses:,}", "queries with no relevant chunk"),
        ]
        items = "".join(
            f'<div class="card tile"><div class="number">{escape(number)}</div>'
            f'<div class="caption">{escape(caption)}</div></div>'
            for number, caption in tiles
        )
        return f'<section class="tiles">{items}</section>'

    @staticmethod
    def _section(title: str, content: str) -> str:
        return f'<section class="card">\n<h2>{escape(title)}</h2>\n{content}\n</section>'

    @staticmethod
    def _queries(report: EvaluationReport) -> str:
        rows = [
            (
                outcome.case.query,
                ", ".join(outcome.case.relevant),
                _first_hit(outcome),
                f"{outcome.recall:.0%}",
            )
            for outcome in report.outcomes
        ]
        return text_table(("Query", "Relevant", "First hit", f"Recall@{report.k}"), rows)


class TextEvaluationRenderer:
    """The evaluation's numbers for terminals and text-only clients."""

    def render(self, report: EvaluationReport) -> str:
        lines = [
            f"Queries:              {len(report.outcomes):,}",
            f"{f'Recall@{report.k}:':<21} {report.recall:.0%}",
            f"Mean reciprocal rank: {report.mrr:.2f}",
        ]
        if report.outcomes:
            lines += ["", "Recall by cut-off:", *_bars(recall_rows(report))]
            lines += ["", "Queries (first hit, recall):"]
            width = max(len(_first_hit(outcome)) for outcome in report.outcomes)
            lines += [
                f"  {_first_hit(outcome):>{width}}  {outcome.recall:>4.0%}  {outcome.case.query}"
                for outcome in report.outcomes
            ]
        return "\n".join(lines) + "\n"


def recall_rows(report: EvaluationReport) -> list[tuple[str, float]]:
    """``("top 1", recall@1)``, ``("top 2", recall@2)``... for charts and tables."""
    return [(f"top {cut}", value) for cut, value in enumerate(report.recall_curve, start=1)]


def _bars(rows: list[tuple[str, float]]) -> list[str]:
    names = max(len(name) for name, _ in rows)
    return [
        f"  {name:<{names}}  {'█' * round(BAR_WIDTH * value)} {value:.0%}"
        for name, value in rows
    ]


def _first_hit(outcome: CaseOutcome) -> str:
    return f"#{outcome.first_hit}" if outcome.first_hit else "miss"


def _query_label(outcome: CaseOutcome) -> str:
    query = outcome.case.query
    return query if len(query) <= 40 else query[:39] + "…"
