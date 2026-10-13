from docsage.domain.models import CaseOutcome, EvaluationCase, EvaluationReport
from docsage.infrastructure.evaluation_report import (
    HtmlEvaluationRenderer,
    TextEvaluationRenderer,
    recall_rows,
)


def report():
    install = EvaluationCase("how to install", ("install.md",))
    hit = CaseOutcome(install, ("install.md",), 1, (1.0, 1.0))
    scores = EvaluationCase("bm25 <scores>", ("retrieval.md",))
    late = CaseOutcome(scores, ("faq.txt", "retrieval.md"), 2, (0.0, 1.0))
    miss = CaseOutcome(EvaluationCase("docker", ("deploy.md",)), ("faq.txt",), None, (0.0, 0.0))
    return EvaluationReport(k=2, outcomes=(hit, late, miss))


def test_recall_rows_label_each_cut_off():
    assert recall_rows(report()) == [("top 1", 1 / 3), ("top 2", 2 / 3)]


def test_html_report_shows_tiles_charts_and_queries():
    html = HtmlEvaluationRenderer().render(report())

    assert html.startswith("<!doctype html>")
    assert "prefers-color-scheme: dark" in html
    assert "67%</div>" in html and "recall@2" in html
    assert "0.50</div>" in html and "mean reciprocal rank" in html
    assert 'aria-label="Mean recall at each cut-off"' in html
    assert 'aria-label="Reciprocal rank per query"' in html
    assert "bm25 &lt;scores&gt;" in html and "<scores>" not in html
    assert "<td>miss</td>" in html and "<td>#2</td>" in html
    assert "http" not in html.replace('xmlns="http', "")


def test_html_report_without_queries_has_no_charts():
    html = HtmlEvaluationRenderer().render(EvaluationReport(k=3, outcomes=()))

    assert "<svg" not in html
    assert "0 labeled queries" in html


def test_text_report_lists_metrics_bars_and_queries():
    text = TextEvaluationRenderer().render(report())

    assert "Queries:              3" in text
    assert "Recall@2:             67%" in text
    assert "Mean reciprocal rank: 0.50" in text
    assert "  top 2  " + "█" * 20 + " 67%" in text
    assert "    #1  100%  how to install" in text
    assert "  miss    0%  docker" in text
