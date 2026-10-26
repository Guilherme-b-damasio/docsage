import pytest

from docsage.domain.models import Answer, Chunk, Document, Highlight, SearchResult
from docsage.infrastructure.loaders import PAGE_SEPARATOR, page_offsets


def test_page_offsets_follow_the_joined_text():
    pages = ["first", "second page", ""]
    text = PAGE_SEPARATOR.join(pages)

    offsets = page_offsets(pages)

    assert offsets == (0, 7, 20)
    assert text[offsets[1] :].startswith("second")


@pytest.mark.parametrize("offset,page", [(0, 1), (6, 1), (7, 2), (19, 2), (20, 3), (99, 3)])
def test_document_maps_offsets_to_pages(offset, page):
    document = Document(source="a.pdf", text="x" * 30, page_offsets=(0, 7, 20))
    assert document.page_at(offset) == page


def test_unpaged_document_has_no_page():
    assert Document(source="a.md", text="hello").page_at(0) is None


@pytest.mark.parametrize(
    "first,last,expected",
    [
        (None, None, "a.pdf"),
        (3, 3, "a.pdf, p. 3"),
        (3, None, "a.pdf, p. 3"),
        (3, 4, "a.pdf, pp. 3-4"),
    ],
)
def test_chunk_citation_includes_page_range(first, last, expected):
    chunk = Chunk(id="x", source="a.pdf", text="", position=0, first_page=first, last_page=last)
    assert chunk.citation == expected


def test_chunk_citation_prefers_the_section():
    chunk = Chunk(id="x", source="a.md", text="", position=0, section="Setup > Install")
    assert chunk.citation == "a.md, Setup > Install"


def test_search_result_lists_matched_terms_once_in_text_order():
    chunk = Chunk(id="a#0", source="a.md", text="Index the index, then search.", position=0)
    highlights = (
        Highlight(0, 5, "index"),
        Highlight(10, 15, "index"),
        Highlight(22, 28, "search"),
    )

    result = SearchResult(chunk, 1.0, highlights)

    assert result.matched_terms == ("index", "search")
    assert [chunk.text[item.start : item.end] for item in highlights] == [
        "Index",
        "index",
        "search",
    ]


def test_search_result_has_no_highlights_by_default():
    result = SearchResult(Chunk(id="a#0", source="a.md", text="x", position=0), 0.5)

    assert result.highlights == ()
    assert result.matched_terms == ()


def test_answer_style_defaults_and_rejects_unknown_lengths():
    import pytest

    from docsage.domain.models import AnswerStyle

    assert AnswerStyle() == AnswerStyle(language="", length="medium")
    with pytest.raises(ValueError, match="Unknown answer length"):
        AnswerStyle(length="huge")


@pytest.mark.parametrize(
    "pattern,source,matches",
    [
        ("", "docs/faq.md", True),
        (".md", "docs/faq.md", True),
        (".md", "docs/faq.pdf", False),
        ("*.pdf", "manual.PDF", True),
        (".md", "notes.markdown", False),
        ("docs", "project/docs/faq.md", True),
        ("docs", "docsage/faq.md", False),
        ("docs/api", "project/docs/api/v1.md", True),
        ("docs/api", "project/api/docs/v1.md", False),
        ("docs\\api", "project/docs/api/v1.md", True),
        ("DOCS", "project/docs/faq.md", True),
        ("docs/faq.md", "docs/faq.md", True),
        ("https://example.com/docs", "https://example.com/docs/intro", True),
        ("https://example.com/docs", "https://example.com/blog/intro", False),
    ],
)
def test_source_filter_matches_types_folders_and_urls(pattern, source, matches):
    from docsage.domain.models import SourceFilter

    assert SourceFilter(pattern).matches(source) is matches


def test_empty_source_filter_is_falsey_so_callers_can_skip_it():
    from docsage.domain.models import SourceFilter

    assert not SourceFilter()
    assert not SourceFilter("  ")
    assert SourceFilter(".md")


def test_source_view_exposes_the_marked_passage():
    from docsage.domain.models import SourceView

    view = SourceView("notes.md", "intro\npassage here\noutro", 6, 18)

    assert view.passage == "passage here"


def test_source_view_without_a_passage_has_an_empty_one():
    from docsage.domain.models import SourceView

    assert SourceView("notes.md", "intro").passage == ""


@pytest.mark.parametrize(
    "start, end",
    [(0, None), (None, 3), (-1, 3), (4, 2), (0, 99)],
)
def test_source_view_rejects_a_passage_outside_the_text(start, end):
    from docsage.domain.models import SourceView

    with pytest.raises(ValueError):
        SourceView("notes.md", "intro", start, end)


def _cited(source, rank_text, indexed_at=""):
    chunk = Chunk(f"{source}#{rank_text}", source, rank_text, 0, indexed_at=indexed_at)
    return SearchResult(chunk, 1.0)


def test_cited_documents_groups_passages_of_the_same_document():
    answer = Answer(
        "q",
        "a",
        (
            _cited("a.md", "first", "2026-10-01T00:00:00+00:00"),
            _cited("b.md", "second", "2026-10-01T00:00:00+00:00"),
            _cited("a.md", "third", "2026-10-01T00:00:00+00:00"),
        ),
    )

    documents = answer.cited_documents()

    assert [document.source for document in documents] == ["a.md", "b.md"]
    assert [citation.rank for citation in documents[0].citations] == [1, 3]
    assert [citation.rank for citation in documents[1].citations] == [2]


def test_cited_documents_puts_the_newest_document_first():
    answer = Answer(
        "q",
        "a",
        (
            _cited("old.md", "first", "2026-01-01T00:00:00+00:00"),
            _cited("new.md", "second", "2026-10-01T00:00:00+00:00"),
        ),
    )

    assert [document.source for document in answer.cited_documents()] == ["new.md", "old.md"]


def test_cited_documents_without_an_index_time_come_last():
    answer = Answer(
        "q",
        "a",
        (_cited("unknown.md", "first"), _cited("dated.md", "second", "2026-01-01T00:00:00+00:00")),
    )

    documents = answer.cited_documents()

    assert [document.source for document in documents] == ["dated.md", "unknown.md"]
    assert documents[1].indexed_at == ""


def test_cited_documents_indexed_together_keep_their_best_rank_order():
    same = "2026-10-01T00:00:00+00:00"
    answer = Answer("q", "a", (_cited("b.md", "first", same), _cited("a.md", "second", same)))

    assert [document.source for document in answer.cited_documents()] == ["b.md", "a.md"]


def test_cited_document_reports_its_best_rank_and_newest_passage():
    answer = Answer(
        "q",
        "a",
        (
            _cited("a.md", "first", "2026-01-01T00:00:00+00:00"),
            _cited("a.md", "second", "2026-10-01T00:00:00+00:00"),
        ),
    )

    document = answer.cited_documents()[0]

    assert (document.best_rank, document.indexed_at) == (1, "2026-10-01T00:00:00+00:00")


def test_an_answer_without_sources_cites_no_documents():
    assert Answer("q", "nothing", ()).cited_documents() == ()


def _compared(label, *ids):
    from docsage.domain.models import ComparedAnswer

    sources = tuple(SearchResult(Chunk(id, "a.md", id, 0), 1.0) for id in ids)
    return ComparedAnswer(label, Answer("what?", f"{label} answer", sources))


def test_a_comparison_knows_the_passages_both_answers_share():
    from docsage.domain.models import AnswerComparison

    left, right = _compared("bm25", "a#0", "a#1"), _compared("hybrid", "a#1", "a#2")
    comparison = AnswerComparison(left, right)

    assert comparison.question == "what?"
    assert comparison.shared_chunks() == frozenset({"a#1"})
    assert comparison.overlap() == pytest.approx(1 / 3)


def test_two_answers_without_passages_overlap_fully():
    from docsage.domain.models import AnswerComparison

    assert AnswerComparison(_compared("left"), _compared("right")).overlap() == 1.0
