import json

from docsage.domain.models import Answer, Chunk, SearchResult
from docsage.interfaces.serializers import (
    answer_to_dict,
    dumps,
    search_results_to_dict,
)


def _result(text: str, score: float) -> SearchResult:
    return SearchResult(Chunk(id=f"a.md#{score}", source="a.md", text=text, position=0), score)


def test_search_results_are_ranked_and_rounded():
    payload = search_results_to_dict("alpha", [_result("one", 2.123456), _result("two", 1.0)])

    assert payload["query"] == "alpha"
    assert [r["rank"] for r in payload["results"]] == [1, 2]
    assert payload["results"][0]["score"] == 2.1235
    assert payload["results"][0]["chunk"] == {
        "id": "a.md#2.123456",
        "source": "a.md",
        "position": 0,
        "text": "one",
    }


def test_answer_includes_question_text_and_sources():
    answer = Answer("why?", "because [1]", (_result("ctx", 1.5),))

    payload = answer_to_dict(answer)

    assert payload["question"] == "why?"
    assert payload["answer"] == "because [1]"
    assert payload["sources"][0]["rank"] == 1
    assert payload["sources"][0]["chunk"]["source"] == "a.md"


def test_dumps_keeps_non_ascii_text():
    text = dumps(search_results_to_dict("ação", []))

    assert "ação" in text
    assert json.loads(text) == {"query": "ação", "results": []}
