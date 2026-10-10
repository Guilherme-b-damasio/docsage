import json

from docsage.application.services import IndexingReport, RemovalReport
from docsage.domain.models import Answer, Chunk, Highlight, SearchResult
from docsage.interfaces.serializers import (
    answer_to_dict,
    dumps,
    indexing_report_to_dict,
    removal_report_to_dict,
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
        "first_page": None,
        "last_page": None,
        "section": "",
        "citation": "a.md",
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


def test_chunk_page_range_is_serialized():
    chunk = Chunk(id="p", source="a.pdf", text="t", position=0, first_page=2, last_page=3)

    payload = search_results_to_dict("q", [SearchResult(chunk, 1.0)])

    assert payload["results"][0]["chunk"]["citation"] == "a.pdf, pp. 2-3"
    assert payload["results"][0]["chunk"]["first_page"] == 2


def test_chunk_section_is_serialized():
    chunk = Chunk(id="s", source="a.md", text="t", position=0, section="Guide > Install")

    payload = search_results_to_dict("q", [SearchResult(chunk, 1.0)])["results"][0]["chunk"]

    assert payload["section"] == "Guide > Install"
    assert payload["citation"] == "a.md, Guide > Install"


def test_indexing_report_lists_skipped_files():
    report = IndexingReport(documents=2, chunks=5, skipped=("a.png",), unchanged=1)

    assert indexing_report_to_dict(report) == {
        "documents": 2,
        "chunks": 5,
        "unchanged": 1,
        "skipped": ["a.png"],
    }


def test_removal_report_keeps_the_requested_path():
    report = RemovalReport(documents=("docs/a.md", "docs/b.md"), chunks=3)

    assert removal_report_to_dict("docs", report) == {
        "path": "docs",
        "documents": ["docs/a.md", "docs/b.md"],
        "chunks": 3,
    }


def test_search_results_include_matched_terms_and_offsets():
    chunk = Chunk(id="a#0", source="a.md", text="Index the index", position=0)
    highlights = (Highlight(0, 5, "index"), Highlight(10, 15, "index"))

    (payload,) = search_results_to_dict("index", [SearchResult(chunk, 1.0, highlights)])[
        "results"
    ]

    assert payload["matched_terms"] == ["index"]
    assert payload["highlights"] == [
        {"start": 0, "end": 5, "term": "index"},
        {"start": 10, "end": 15, "term": "index"},
    ]


def test_results_without_highlights_serialize_empty_lists():
    (payload,) = search_results_to_dict("x", [_result("one", 1.0)])["results"]

    assert payload["matched_terms"] == []
    assert payload["highlights"] == []
