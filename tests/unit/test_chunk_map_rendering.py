from docsage.domain.models import ChunkPoint, HistogramBin, IndexOverview
from docsage.infrastructure.html_dashboard import HtmlDashboardRenderer, map_groups
from docsage.infrastructure.svg_charts import CHART_CSS, SERIES, legend, scatter_chart
from docsage.infrastructure.text_dashboard import TextDashboardRenderer, map_lines


def _overview(points):
    return IndexOverview(
        documents=2,
        chunks=len(points),
        terms=10,
        vocabulary=5,
        index_bytes=100,
        documents_by_type=(("md", 2),),
        chunk_lengths=(HistogramBin(1, 3, len(points)),),
        top_terms=(("alpha", 2),),
        chunk_map=tuple(points),
    )


POINTS = [
    ChunkPoint("a#0", "docs/a.md", -1.0, 1.0),
    ChunkPoint("a#1", "docs/a.md", -0.9, 0.8),
    ChunkPoint("b#0", "docs/z<b>.md", 1.0, -1.0),
]


def test_scatter_chart_places_dots_by_coordinates_with_tooltips():
    svg = scatter_chart([(-1.0, 1.0, 0, "first"), (1.0, -1.0, 9, "<second>")], "Map")

    assert 'aria-label="Map"' in svg
    assert svg.count('class="dot ') == 2
    assert 'class="dot series-1" cx="16.0" cy="16.0"' in svg
    assert 'class="dot series-other" cx="784.0" cy="344.0"' in svg
    assert "<title>&lt;second&gt;</title>" in svg
    assert scatter_chart([], "Map") == ""


def test_series_colors_are_defined_for_light_and_dark_mode():
    assert CHART_CSS.count("--series-1: ") == 3
    assert ':root[data-theme="dark"]' in CHART_CSS
    assert ".series-other { --series: var(--series-other); }" in CHART_CSS


def test_legend_names_each_series_in_order():
    html = legend(["a.md", "<b>"])

    assert html.index("series-1") < html.index("a.md") < html.index("series-2")
    assert "&lt;b&gt;" in html


def test_groups_fold_documents_beyond_the_palette_into_other():
    sources = [f"doc{n:02}.md" for n in range(SERIES + 2)]

    groups = map_groups(sources)

    assert groups["doc00.md"] == ("doc00.md", 0)
    assert groups[f"doc{SERIES - 2:02}.md"][1] == SERIES - 2
    assert {groups[s] for s in sources[SERIES - 1 :]} == {("Other", SERIES - 1)}
    assert map_groups(["b.md", "a.md"]) == {"a.md": ("a.md", 0), "b.md": ("b.md", 1)}


def test_html_dashboard_shows_the_chunk_map_with_legend_and_table():
    html = HtmlDashboardRenderer().render(_overview(POINTS))

    assert "<h2>Chunk map</h2>" in html
    assert html.count('class="dot ') == 3
    assert '<span class="swatch series-2"></span>z&lt;b&gt;.md' in html
    assert "<td>b#0</td><td>z&lt;b&gt;.md</td><td>1.00</td><td>-1.00</td>" in html


def test_html_dashboard_has_no_map_without_points():
    assert "Chunk map" not in HtmlDashboardRenderer().render(_overview([]))


def test_text_map_draws_letters_on_a_framed_grid():
    lines = map_lines(POINTS, width=5, height=3)

    assert lines[:5] == [
        "  +-----+",
        "  |a    |",
        "  |     |",
        "  |    b|",
        "  +-----+",
    ]
    assert lines[5:] == ["  a = a.md", "  b = z<b>.md"]


def test_text_map_marks_cells_shared_by_different_documents():
    points = [ChunkPoint("a", "a.md", 0.0, 0.0), ChunkPoint("b", "b.md", 0.0, 0.0)]

    assert map_lines(points, width=3, height=3)[2] == "  | * |"


def test_text_dashboard_includes_the_map_only_when_present():
    with_map = TextDashboardRenderer().render(_overview(POINTS))

    assert "Chunk map (PCA of embeddings):" in with_map
    assert "Chunk map" not in TextDashboardRenderer().render(_overview([]))
