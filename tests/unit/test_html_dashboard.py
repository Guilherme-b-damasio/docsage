import re

from docsage.domain.models import HistogramBin, IndexOverview
from docsage.infrastructure.html_dashboard import HtmlDashboardRenderer
from docsage.infrastructure.svg_charts import bar_chart, column_chart, data_table


def _overview(**changes):
    values = dict(
        documents=3,
        chunks=4,
        terms=40,
        vocabulary=12,
        index_bytes=2048,
        documents_by_type=(("md", 2), ("pdf", 1)),
        chunk_lengths=(HistogramBin(1, 4, 3), HistogramBin(5, 5, 1)),
        top_terms=(("alpha", 3), ("<beta>", 2)),
    )
    values.update(changes)
    return IndexOverview(**values)


def test_bar_chart_draws_one_mark_per_row_with_tooltips():
    svg = bar_chart([("md", 4), ("pdf", 2)], "Docs")

    assert svg.startswith('<svg class="chart"') and 'aria-label="Docs"' in svg
    assert svg.count('class="bar"') == 2
    assert "<title>md: 4</title>" in svg and "<title>pdf: 2</title>" in svg


def test_bar_chart_scales_bars_to_the_largest_value():
    svg = bar_chart([("a", 10), ("b", 5)], "x")
    paths = re.findall(r'd="M([\d.]+),[\d.]+H[\d.]+A[\d.]+,[\d.]+ 0 0 1 ([\d.]+),', svg)
    (left, right_a), (_, right_b) = [(float(x), float(y)) for x, y in paths]

    assert abs((right_a - left) / (right_b - left) - 2) < 0.01


def test_bar_chart_clips_long_names_and_handles_zero():
    svg = bar_chart([("x" * 80, 0)], "x")

    assert "…" in svg
    assert "<title>" + "x" * 80 + ": 0</title>" in svg


def test_column_chart_labels_only_non_empty_columns():
    svg = column_chart([("1–4", 3), ("5–8", 0)], "Lengths")

    assert svg.count('class="bar"') == 2
    assert svg.count('class="value"') == 1
    assert ">1–4</text>" in svg and ">5–8</text>" in svg


def test_empty_charts_render_nothing():
    assert bar_chart([], "x") == "" and column_chart([], "x") == ""


def test_data_table_escapes_names():
    html = data_table(("Term", "Count"), [("<b>", 1200)])
    assert "<td>&lt;b&gt;</td><td>1,200</td>" in html


def test_dashboard_has_tiles_three_charts_and_tables():
    html = HtmlDashboardRenderer().render(_overview())

    assert html.startswith("<!doctype html>")
    assert "prefers-color-scheme: dark" in html
    assert html.count('<svg class="chart"') == 3
    assert html.count("Show as table") == 3
    assert ">2.0 KB<" in html and "distinct terms of 40" in html
    assert "&lt;beta&gt;" in html and "<beta>" not in html
    assert "<td>5</td><td>1</td>" in html


def test_dashboard_needs_no_network():
    html = HtmlDashboardRenderer().render(_overview())
    assert not re.search(r"(src|href)=\"https?://", html)
    assert "<script" not in html


def test_empty_dashboard_explains_how_to_index():
    html = HtmlDashboardRenderer().render(
        _overview(documents=0, chunks=0, documents_by_type=(), chunk_lengths=(), top_terms=())
    )

    assert "The index is empty" in html
    assert "<svg" not in html
