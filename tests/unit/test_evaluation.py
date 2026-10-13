import pytest

from docsage.application.services import EvaluationService, source_matches
from docsage.domain.models import Chunk, EvaluationCase, EvaluationReport, SearchResult


class FixedRetriever:
    """Returns a canned ranking of sources per query."""

    def __init__(self, rankings):
        self._rankings = rankings
        self.calls = []

    def search(self, query, top_k):
        self.calls.append((query, top_k))
        sources = self._rankings.get(query, [])[:top_k]
        return [
            SearchResult(Chunk(id=f"{source}-{rank}", source=source, text="", position=rank), 1.0)
            for rank, source in enumerate(sources)
        ]


class EchoRenderer:
    def render(self, report):
        return f"recall={report.recall:.2f}"


def service(rankings):
    return EvaluationService(FixedRetriever(rankings), EchoRenderer())


def test_recall_and_reciprocal_rank_per_query():
    report = service({"q": ["/c/other.md", "/c/a.md", "/c/a.md", "/c/b.md"]}).evaluate(
        [EvaluationCase("q", ("a.md", "b.md"))], k=4
    )

    outcome = report.outcomes[0]
    assert outcome.first_hit == 2
    assert outcome.reciprocal_rank == 0.5
    assert outcome.recall_curve == (0.0, 0.5, 0.5, 1.0)
    assert outcome.recall == 1.0
    assert outcome.ranked_sources == ("/c/other.md", "/c/a.md", "/c/a.md", "/c/b.md")


def test_report_averages_over_queries():
    report = service({"hit": ["a.md"], "miss": ["z.md"]}).evaluate(
        [EvaluationCase("hit", ("a.md",)), EvaluationCase("miss", ("a.md",))], k=2
    )

    assert report.k == 2
    assert report.recall_curve == (0.5, 0.5)
    assert report.recall == 0.5
    assert report.mrr == 0.5
    assert report.outcomes[1].first_hit is None
    assert report.outcomes[1].reciprocal_rank == 0.0


def test_fewer_results_than_k_keep_a_full_length_curve():
    report = service({"q": ["a.md"]}).evaluate([EvaluationCase("q", ("a.md",))], k=3)

    assert report.outcomes[0].recall_curve == (1.0, 1.0, 1.0)


def test_retriever_is_asked_for_k_results():
    retriever = FixedRetriever({})
    EvaluationService(retriever, EchoRenderer()).evaluate([EvaluationCase("q", ("a",))], k=7)

    assert retriever.calls == [("q", 7)]


def test_empty_report_scores_zero():
    report = EvaluationReport(k=5, outcomes=())

    assert (report.recall, report.mrr, report.recall_curve) == (0.0, 0.0, ())


def test_k_must_be_positive():
    with pytest.raises(ValueError, match="k must be"):
        service({}).evaluate([], k=0)


def test_render_delegates_to_the_renderer():
    evaluation = service({"q": ["a.md"]})

    assert evaluation.render(evaluation.evaluate([EvaluationCase("q", ("a.md",))])) == (
        "recall=1.00"
    )


@pytest.mark.parametrize(
    ("source", "label", "expected"),
    [
        ("faq.md", "faq.md", True),
        ("/home/me/docs/faq.md", "docs/faq.md", True),
        (r"C:\notes\docs\faq.md", "docs/faq.md", True),
        ("/home/me/myfaq.md", "faq.md", False),
        ("/home/me/faq.md", "", False),
    ],
)
def test_source_matches_full_paths_and_path_suffixes(source, label, expected):
    assert source_matches(source, label) is expected
