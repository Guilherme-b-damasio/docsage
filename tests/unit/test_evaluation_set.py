import json

import pytest

from docsage.domain.models import EvaluationCase
from docsage.infrastructure.evaluation_set import EvaluationSetError, read_evaluation_set


def write(tmp_path, content):
    path = tmp_path / "labels.json"
    path.write_text(content if isinstance(content, str) else json.dumps(content), "utf-8")
    return path


def test_reads_a_top_level_list(tmp_path):
    path = write(tmp_path, [{"query": " where is the index? ", "relevant": ["faq.txt"]}])

    assert read_evaluation_set(path) == [EvaluationCase("where is the index?", ("faq.txt",))]


def test_reads_cases_under_a_key_and_accepts_a_single_source(tmp_path):
    path = write(tmp_path, {"cases": [{"query": "bm25", "relevant": "retrieval.md"}]})

    assert read_evaluation_set(path) == [EvaluationCase("bm25", ("retrieval.md",))]


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("{not json", "Invalid JSON"),
        ([], "non-empty list"),
        ({"cases": "nope"}, "non-empty list"),
        (["text"], "Case 1 .* must be an object"),
        ([{"query": "", "relevant": ["a"]}], "Case 1 .* non-empty query"),
        ([{"query": "q", "relevant": []}], "Case 1 .* relevant"),
        ([{"query": "q", "relevant": ["a"]}, {"query": "q", "relevant": [3]}], "Case 2"),
    ],
)
def test_rejects_malformed_files(tmp_path, content, message):
    with pytest.raises(EvaluationSetError, match=message):
        read_evaluation_set(write(tmp_path, content))


def test_missing_file(tmp_path):
    with pytest.raises(EvaluationSetError, match="not found"):
        read_evaluation_set(tmp_path / "missing.json")
