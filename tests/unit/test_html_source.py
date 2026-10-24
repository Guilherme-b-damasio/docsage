import pytest

from docsage.domain.models import Highlight, SourceView
from docsage.infrastructure.html_source import HtmlSourceRenderer

TEXT = "# Alpha\n\nalpha notes about retrieval\n\nthe end\n"
PASSAGE_START = TEXT.index("alpha notes")
PASSAGE_END = PASSAGE_START + len("alpha notes about retrieval")


@pytest.fixture
def view():
    return SourceView(
        source="docs/a.md",
        text=TEXT,
        passage_start=PASSAGE_START,
        passage_end=PASSAGE_END,
        highlights=(Highlight(PASSAGE_START, PASSAGE_START + 5, "alpha"),),
    )


def test_renders_a_complete_page_titled_after_the_source(view):
    html = HtmlSourceRenderer().render(view)

    assert html.startswith("<!doctype html>")
    assert "<title>docsage: docs/a.md</title>" in html
    assert html.rstrip().endswith("</html>")


def test_marks_the_passage_in_place_with_the_text_around_it(view):
    html = HtmlSourceRenderer().render(view)

    assert '<pre class="passage" id="passage"' in html
    assert "<pre># Alpha\n\n</pre>" in html
    assert "<pre>\n\nthe end\n</pre>" in html
    assert 'href="#passage"' in html


def test_highlights_the_matched_terms_inside_the_passage(view):
    html = HtmlSourceRenderer().render(view)

    assert '<mark title="alpha">alpha</mark> notes about retrieval' in html
    assert "with its matched term marked" in html


def test_counts_several_matched_terms_in_the_summary():
    view = SourceView(
        "a.md",
        "alpha beta",
        0,
        10,
        (Highlight(0, 5, "alpha"), Highlight(6, 10, "beta")),
    )

    assert "with its 2 matched terms marked" in HtmlSourceRenderer().render(view)


def test_drops_highlights_that_fall_outside_the_passage():
    view = SourceView("a.md", "alpha beta", 6, 10, (Highlight(0, 5, "alpha"),))

    html = HtmlSourceRenderer().render(view)

    assert "<mark" not in html
    assert "The cited passage is highlighted below." in html


def test_renders_the_whole_document_when_no_passage_is_marked():
    html = HtmlSourceRenderer().render(SourceView("a.md", "alpha <b>beta</b>"))

    assert "<pre>alpha &lt;b&gt;beta&lt;/b&gt;</pre>" in html
    assert "Indexed by docsage." in html
    assert 'href="#passage"' not in html


def test_escapes_the_text_around_and_inside_the_passage():
    text = "<script>a</script>alpha<script>b</script>"
    view = SourceView("a.md", text, 18, 23, (Highlight(18, 23, "alpha"),))

    html = HtmlSourceRenderer().render(view)

    assert "<script>" not in html
    assert "&lt;script&gt;a&lt;/script&gt;" in html


@pytest.mark.parametrize(
    "source, supported",
    [
        ("docs/a.md", True),
        ("notes.MARKDOWN", True),
        ("notes.txt", True),
        ("guide.rst", True),
        ("manual.pdf", False),
        ("report.docx", False),
        ("page.html", False),
        ("https://example.com/guide.md", False),
    ],
)
def test_supports_only_plain_text_formats(source, supported):
    assert HtmlSourceRenderer().supports(source) is supported


def test_defines_the_passage_color_for_light_and_dark_mode(view):
    html = HtmlSourceRenderer().render(view)

    assert "--passage-bg" in html
    assert 'prefers-color-scheme: dark' in html
    assert ':root[data-theme="dark"]' in html
