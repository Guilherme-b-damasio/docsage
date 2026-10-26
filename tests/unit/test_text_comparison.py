from docsage.domain.models import Answer, AnswerComparison, Chunk, ComparedAnswer, SearchResult
from docsage.infrastructure.text_comparison import TextComparisonRenderer


def _result(chunk_id, score=1.0):
    return SearchResult(Chunk(chunk_id, "a.md", "alpha notes", 0), score)


def test_text_comparison_lists_both_answers_and_marks_shared_passages():
    left = Answer("alpha?", "Left answer [1].", (_result("a#0", 2.0),))
    right = Answer("alpha?", "Right answer.", (_result("a#0"), _result("a#1")))
    comparison = AnswerComparison(ComparedAnswer("bm25", left), ComparedAnswer("hybrid", right))

    lines = TextComparisonRenderer().render(comparison).splitlines()

    assert lines[:4] == ["alpha?", "======", "", "1 passage in both answers (50% overlap)"]
    assert lines.index("bm25") < lines.index("Left answer [1].") < lines.index("hybrid")
    assert "[1] a.md (score 2.00) (in both)" in lines
    assert "[2] a.md (score 1.00)" in lines


def test_text_comparison_without_passages():
    empty = Answer("alpha?", "No relevant context found in the index.", ())
    comparison = AnswerComparison(ComparedAnswer("a", empty), ComparedAnswer("b", empty))

    out = TextComparisonRenderer().render(comparison)

    assert "0 passages in both answers (100% overlap)" in out
    assert "[1]" not in out
