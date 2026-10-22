import re

from docsage.domain.models import DocumentRelation, HistogramBin, IndexOverview, RecentDocument
from docsage.infrastructure.html_dashboard import HtmlDashboardRenderer
from docsage.infrastructure.svg_charts import bar_chart, column_chart, data_table, network_chart


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


def test_bar_chart_and_table_accept_a_value_format():
    two_decimals = "{:.2f}".format
    svg = bar_chart([("bm25", 1.23456), ("rank", 0.5)], "Breakdown", two_decimals)
    table = data_table(("Term", "Score"), [("bm25", 1.23456)], two_decimals)

    assert "<title>bm25: 1.23</title>" in svg
    assert ">0.50</text>" in svg
    assert "<td>1.23</td>" in table


RELATIONS = (
    DocumentRelation("docs/a.md", "docs/b.md", ("bm25", "ranking", "index")),
    DocumentRelation("docs/a.md", "c.pdf", ("<install>",)),
)


def test_network_chart_draws_nodes_and_weighted_edges():
    svg = network_chart(["a", "b", "c"], [(0, 1, 3, "a-b"), (0, 2, 1, "a-c")], "Graph")

    assert svg.count('class="node"') == 3
    assert svg.count('class="edge"') == 2
    widths = [float(value) for value in re.findall(r'stroke-width="([\d.]+)"', svg)]
    assert widths[0] > widths[1]
    assert "<title>a-b</title>" in svg


def test_network_chart_places_names_outside_the_circle():
    svg = network_chart(["left", "right"], [(0, 1, 1, "x")], "Graph")

    assert 'text-anchor="end" dominant-baseline="central">left<' in svg
    assert 'text-anchor="start" dominant-baseline="central">right<' in svg


def test_empty_network_chart_renders_nothing():
    assert network_chart([], [], "x") == ""


def test_dashboard_shows_related_documents_with_a_table_and_mermaid_source():
    html = HtmlDashboardRenderer().render(_overview(relations=RELATIONS))

    assert html.count('<svg class="chart"') == 4
    assert "Related documents" in html
    assert "<title>a.md ↔ b.md: bm25, ranking, index</title>" in html
    assert "<td>a.md ↔ b.md (bm25, ranking, index)</td><td>3</td>" in html
    assert "Mermaid source" in html and "graph LR" in html
    assert "&lt;install&gt;" in html and "<install>" not in html


def test_dashboard_without_relations_has_no_relations_section():
    assert "Related documents" not in HtmlDashboardRenderer().render(_overview())


def test_dashboard_lists_recently_indexed_documents_with_chunk_meters():
    recent = (
        RecentDocument("docs/<new>.md", "2026-10-22T09:30:00+00:00", 4),
        RecentDocument("old.md", "", 1),
    )

    html = HtmlDashboardRenderer().render(_overview(recent_documents=recent))

    assert "<h2>Recently indexed</h2>" in html
    assert "<td>docs/&lt;new&gt;.md</td>" in html
    assert '<time datetime="2026-10-22T09:30:00+00:00">2026-10-22 09:30 UTC</time>' in html
    assert "<td>unknown</td>" in html
    assert 'style="width: 48px"></span>4</td>' in html
    assert 'style="width: 12px"></span>1</td>' in html
    assert html.index("Recently indexed") < html.index("Documents per file type")


def test_dashboard_without_recent_documents_has_no_recent_section():
    assert "Recently indexed" not in HtmlDashboardRenderer().render(_overview())
