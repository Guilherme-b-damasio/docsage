from docsage.domain.models import Answer, Chunk, Highlight, SearchResult
from docsage.infrastructure.text_report import TextAnswerRenderer, emphasized


def test_emphasized_wraps_highlighted_spans():
    spans = [Highlight(0, 5, "alpha"), Highlight(2, 4, "x"), Highlight(6, 99, "y")]
    assert emphasized("alpha beta", spans) == "**alpha** beta"


def test_text_report_lists_numbered_sources_with_emphasis():
    chunk = Chunk("a.md#0", "a.md", "BM25 ranks chunks.\nSecond line.", 0)
    result = SearchResult(chunk, 2.5, (Highlight(0, 4, "bm25"),))

    text = TextAnswerRenderer().render(Answer("What is BM25?", "A ranking [1].", (result,)))

    assert text.splitlines()[:4] == ["What is BM25?", "=============", "", "A ranking [1]."]
    assert "[1] a.md (score 2.50)" in text
    assert "    **BM25** ranks chunks.\n    Second line." in text


def test_text_report_without_sources():
    text = TextAnswerRenderer().render(Answer("Q?", "Nothing found.", ()))
    assert "Sources:" not in text
