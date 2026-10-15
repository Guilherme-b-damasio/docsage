import json

from docsage.application.services import IndexingReport, RemovalReport
from docsage.domain.models import (
    Answer,
    Chunk,
    ChunkPoint,
    DocumentRelation,
    Highlight,
    HistogramBin,
    IndexOverview,
    SearchResult,
    TermScore,
    TokenUsage,
)
from docsage.interfaces.serializers import (
    answer_to_dict,
    dumps,
    indexing_report_to_dict,
    overview_to_dict,
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
    assert payload["contributions"] == []


def test_search_results_include_rounded_term_contributions():
    chunk = Chunk(id="a#0", source="a.md", text="alpha beta", position=0)
    contributions = (TermScore("alpha", 1.234567), TermScore("beta", 0.5))

    (payload,) = search_results_to_dict(
        "alpha beta", [SearchResult(chunk, 1.734567, (), contributions)]
    )["results"]

    assert payload["contributions"] == [
        {"term": "alpha", "score": 1.2346},
        {"term": "beta", "score": 0.5},
    ]


def test_overview_names_every_count():
    overview = IndexOverview(
        documents=2,
        chunks=3,
        terms=30,
        vocabulary=9,
        index_bytes=512,
        documents_by_type=(("md", 2),),
        chunk_lengths=(HistogramBin(1, 4, 2), HistogramBin(5, 8, 1)),
        top_terms=(("alpha", 4),),
        relations=(DocumentRelation("a.md", "b.md", ("alpha", "beta")),),
        chunk_map=(ChunkPoint("a#0", "a.md", 0.5, -1.0),),
    )

    payload = overview_to_dict(overview)

    assert payload["documents_by_type"] == [{"type": "md", "documents": 2}]
    assert payload["chunk_lengths"] == [
        {"low": 1, "high": 4, "chunks": 2},
        {"low": 5, "high": 8, "chunks": 1},
    ]
    assert payload["top_terms"] == [{"term": "alpha", "count": 4}]
    assert payload["index_bytes"] == 512
    assert payload["relations"] == [
        {"first": "a.md", "second": "b.md", "shared_terms": ["alpha", "beta"]}
    ]
    assert payload["chunk_map"] == [{"chunk_id": "a#0", "source": "a.md", "x": 0.5, "y": -1.0}]


def test_answer_usage_and_cost_are_serialized():
    usage = TokenUsage(model="m", input_tokens=10, output_tokens=2, cache_read_input_tokens=5)
    answer = Answer("why?", "because", (), usage=usage, cost_usd=0.00012345678)

    payload = answer_to_dict(answer)

    assert payload["usage"] == {
        "model": "m",
        "input_tokens": 10,
        "output_tokens": 2,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 5,
    }
    assert payload["cost_usd"] == 0.000123
