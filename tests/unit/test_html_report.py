from docsage.domain.models import Answer, Chunk, Highlight, SearchResult, TermScore
from docsage.infrastructure.html_page import highlighted, page
from docsage.infrastructure.html_report import HtmlAnswerRenderer


def _answer(text="BM25 ranks chunks [1].", sources=None):
    chunk = Chunk("a.md#0", "a.md", "BM25 ranks <chunks> by term weight.", 0)
    result = SearchResult(chunk, 1.25, (Highlight(0, 4, "bm25"), Highlight(5, 10, "ranks")))
    return Answer("How does BM25 work?", text, (result,) if sources is None else sources)


def test_page_is_self_contained_and_supports_dark_mode():
    html = page("Title <x>", "<p>body</p>")

    assert html.startswith("<!doctype html>")
    assert "<title>Title &lt;x&gt;</title>" in html
    assert "prefers-color-scheme: dark" in html
    assert "http://" not in html and "https://" not in html


def test_page_lets_a_data_theme_attribute_override_the_system_theme():
    html = page("Title", "<p>body</p>")

    assert ':root:not([data-theme="light"])' in html
    assert ':root[data-theme="dark"]' in html
    dark_rules = html.split(':root[data-theme="dark"]')[1]
    assert "--bg: #0f1216" in dark_rules.split("}")[0]


def test_highlighted_escapes_text_and_marks_spans():
    text = "a <b> c"
    assert highlighted(text, [Highlight(6, 7, "c")]) == 'a &lt;b&gt; <mark title="c">c</mark>'


def test_highlighted_skips_overlapping_and_out_of_range_spans():
    text = "alpha beta"
    spans = [Highlight(0, 5, "alpha"), Highlight(3, 8, "x"), Highlight(6, 99, "y")]
    assert highlighted(text, spans) == '<mark title="alpha">alpha</mark> beta'


def test_report_shows_question_answer_and_highlighted_sources():
    html = HtmlAnswerRenderer().render(_answer())

    assert "<h1>How does BM25 work?</h1>" in html
    assert 'id="source-1"' in html
    assert '<mark title="bm25">BM25</mark> <mark title="ranks">ranks</mark>' in html
    assert "&lt;chunks&gt;" in html
    assert "score 1.25" in html
    assert '<span class="term">bm25</span>' in html


def test_report_links_known_citations_only():
    html = HtmlAnswerRenderer().render(_answer("See [1] and [7].\n\nSecond paragraph."))

    assert '<a class="cite" href="#source-1">[1]</a>' in html
    assert "[7]" in html and 'href="#source-7"' not in html
    assert html.count("<p>") >= 2


def test_report_escapes_the_answer_text():
    html = HtmlAnswerRenderer().render(_answer("<script>alert(1)</script>"))

    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_report_without_sources_has_no_sources_section():
    html = HtmlAnswerRenderer().render(_answer("No relevant context found.", sources=()))

    assert "<h2>Sources</h2>" not in html
    assert "Answered from 0 passages" in html


def test_report_charts_each_sources_score_breakdown():
    chunk = Chunk("a.md#0", "a.md", "BM25 ranks chunks.", 0)
    contributions = (TermScore("bm25", 0.9), TermScore("ranks", 0.35))
    result = SearchResult(chunk, 1.25, (), contributions)

    html = HtmlAnswerRenderer().render(Answer("Q?", "A [1].", (result,)))

    assert "<h3>Score breakdown</h3>" in html
    assert 'aria-label="Score breakdown of source 1"' in html
    assert "<title>bm25: 0.90</title>" in html
    assert "<td>ranks</td><td>0.35</td>" in html


def test_report_omits_the_breakdown_when_the_retriever_gave_none():
    assert "Score breakdown" not in HtmlAnswerRenderer().render(_answer())
