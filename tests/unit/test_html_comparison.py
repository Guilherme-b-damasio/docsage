from docsage.domain.models import (
    Answer,
    AnswerComparison,
    Chunk,
    ComparedAnswer,
    Highlight,
    SearchResult,
    TokenUsage,
)
from docsage.infrastructure.html_comparison import HtmlComparisonRenderer


def _result(chunk_id, text="alpha <notes>"):
    chunk = Chunk(chunk_id, "a.md", text, 0)
    return SearchResult(chunk, 1.5, (Highlight(0, 5, "alpha"),))


def _comparison(left_usage=None):
    left = Answer("what is alpha?", "Alpha [1].", (_result("a#0"),), usage=left_usage)
    right = Answer("what is alpha?", "Alpha [1] and more [2].", (_result("a#0"), _result("a#1")))
    return AnswerComparison(ComparedAnswer("bm25, top 1", left), ComparedAnswer("hybrid", right))


def test_comparison_shows_both_answers_in_columns():
    html = HtmlComparisonRenderer().render(_comparison())

    assert "<h1>what is alpha?</h1>" in html
    assert "bm25, top 1 vs hybrid" in html
    assert html.count('<section class="side"') == 2
    assert "grid-template-columns" in html
    assert "prefers-color-scheme: dark" in html


def test_each_side_links_its_citations_to_its_own_passages():
    html = HtmlComparisonRenderer().render(_comparison())

    assert '<a class="cite" href="#left-1">[1]</a>' in html
    assert '<a class="cite" href="#right-2">[2]</a>' in html
    assert 'id="left-1"' in html and 'id="right-1"' in html and 'id="right-2"' in html
    assert 'id="source-1"' not in html


def test_passages_both_sides_retrieved_are_marked():
    html = HtmlComparisonRenderer().render(_comparison())

    assert html.count('<span class="badge">in both</span>') == 2
    assert "1 passage in both answers" in html
    assert "50% overlap" in html
    assert '<mark title="alpha">alpha</mark> &lt;notes&gt;' in html


def test_comparison_shows_each_side_usage_when_known():
    usage = TokenUsage("claude-opus-5-5", input_tokens=1200, output_tokens=80)

    html = HtmlComparisonRenderer().render(_comparison(usage))

    assert html.count("claude-opus-5-5: 1,200 input tokens") == 1


def test_comparison_escapes_labels():
    comparison = _comparison()
    labelled = AnswerComparison(ComparedAnswer("<b>", comparison.left.answer), comparison.right)

    html = HtmlComparisonRenderer().render(labelled)

    assert "<b>" not in html.split("<body>")[1]
    assert "&lt;b&gt;" in html
