import json
import logging
from types import SimpleNamespace

import pytest

from docsage.domain.models import Chunk, SearchResult
from docsage.infrastructure.claude_reranker import (
    MAX_RELEVANCE,
    ClaudeReranker,
    RerankRefusedError,
    build_prompt,
    parse_grades,
)


class _FakeMessages:
    def __init__(self, response):
        self._response = response
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.messages = _FakeMessages(response)
        self.beta = SimpleNamespace(messages=self.messages)


def _response(stop_reason: str, grades: list[dict] | None = None) -> SimpleNamespace:
    content = []
    if grades is not None:
        content = [SimpleNamespace(type="text", text=json.dumps({"grades": grades}))]
    return SimpleNamespace(
        model="claude-opus-5-5",
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=300, output_tokens=20),
        content=content,
    )


def _candidates() -> list[SearchResult]:
    return [
        SearchResult(Chunk(id=i, source=f"{i}.md", text=f"text {i}", position=0), 5.0 - n)
        for n, i in enumerate("abc")
    ]


def test_candidates_are_sorted_by_grade_and_scored_with_it():
    grades = [
        {"passage": 1, "relevance": 2},
        {"passage": 2, "relevance": 9},
        {"passage": 3, "relevance": 5},
    ]
    reranker = ClaudeReranker(client=_FakeClient(_response("end_turn", grades)))

    results = reranker.rerank("q", _candidates())

    assert [(result.chunk.id, result.score) for result in results] == [
        ("b", 9.0),
        ("c", 5.0),
        ("a", 2.0),
    ]


def test_ties_and_missing_grades_keep_the_first_stage_order():
    grades = [{"passage": 3, "relevance": 4}]
    reranker = ClaudeReranker(client=_FakeClient(_response("end_turn", grades)))

    results = reranker.rerank("q", _candidates())

    assert [result.chunk.id for result in results] == ["c", "a", "b"]
    assert results[1].score == 0.0


def test_requests_structured_output_with_the_effort_and_fallbacks():
    client = _FakeClient(_response("end_turn", []))

    ClaudeReranker(client=client, effort="medium").rerank("where?", _candidates())

    (call,) = client.messages.calls
    assert call["model"] == "claude-opus-5-5"
    assert call["output_config"]["effort"] == "medium"
    assert call["output_config"]["format"]["type"] == "json_schema"
    assert call["fallbacks"] == "default"
    assert "thinking" not in call


def test_raises_and_warns_on_refusal(caplog):
    reranker = ClaudeReranker(client=_FakeClient(_response("refusal")))

    with pytest.raises(RerankRefusedError):
        reranker.rerank("q", _candidates())

    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_no_candidates_makes_no_call():
    client = _FakeClient(_response("end_turn", []))

    assert ClaudeReranker(client=client).rerank("q", []) == []
    assert client.messages.calls == []


def test_parse_grades_clamps_and_ignores_unknown_or_repeated_passages():
    text = json.dumps(
        {
            "grades": [
                {"passage": 1, "relevance": 42},
                {"passage": 1, "relevance": 3},
                {"passage": 2, "relevance": -1},
                {"passage": 7, "relevance": 8},
            ]
        }
    )

    assert parse_grades(text, count=2) == {1: MAX_RELEVANCE, 2: 0}


def test_prompt_numbers_passages_with_their_citation():
    prompt = build_prompt("how?", _candidates()[:1])

    assert "[1] (source: a.md)\ntext a" in prompt
    assert prompt.endswith("Query: how?")
