from docsage.domain.models import IndexStats
from docsage.domain.ports import StatsRenderer
from docsage.infrastructure.html_stats import HtmlStatsRenderer


def _stats(**changes):
    values = dict(
        documents=3,
        chunks=4,
        terms=1200,
        vocabulary=12,
        top_terms=(("alpha", 3), ("<beta>", 2)),
        index_bytes=2048,
    )
    values.update(changes)
    return IndexStats(**values)


def test_renderer_implements_the_port():
    renderer: StatsRenderer = HtmlStatsRenderer()

    assert renderer.render(_stats()).startswith("<!doctype html>")


def test_shows_tiles_for_the_headline_numbers():
    html = HtmlStatsRenderer().render(_stats())

    assert 'aria-label="Summary"' in html
    assert ">3</div>" in html and ">4</div>" in html
    assert "distinct terms of 1,200" in html and "2.0 KB" in html


def test_charts_the_top_terms_with_a_table_and_escapes_them():
    html = HtmlStatsRenderer().render(_stats())

    assert html.count('class="bar"') == 2
    assert "<title>alpha: 3</title>" in html
    assert "&lt;beta&gt;" in html and "<beta>" not in html
    assert "<table" in html


def test_supports_light_and_dark_mode():
    html = HtmlStatsRenderer().render(_stats())

    assert "prefers-color-scheme: dark" in html


def test_empty_index_says_how_to_fill_it():
    html = HtmlStatsRenderer().render(
        _stats(documents=0, chunks=0, terms=0, vocabulary=0, top_terms=())
    )

    assert "The index is empty" in html and "<svg" not in html


def test_no_top_terms_requested_skips_the_chart():
    html = HtmlStatsRenderer().render(_stats(top_terms=()))

    assert "<svg" not in html and "The index is empty" not in html
