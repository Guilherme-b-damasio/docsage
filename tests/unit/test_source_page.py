import pytest

from docsage.application.services import (
    CatalogService,
    SourcePageService,
    UnsupportedFileError,
)
from docsage.domain.models import Chunk
from docsage.domain.text import passage_span
from docsage.infrastructure.bm25 import BM25Retriever
from docsage.infrastructure.highlighting import TermHighlighter
from docsage.infrastructure.loaders import default_loaders
from docsage.infrastructure.tokenizer import multilingual_tokenizer

TEXT = "# Alpha\n\nalpha notes\nabout retrieval\n\n# Beta\n\nbeta notes\n"


class FakeRenderer:
    """Keeps the view it was handed so a test can assert on it instead of on HTML."""

    def __init__(self, supported=True):
        self.supported = supported
        self.view = None

    def supports(self, source):
        return self.supported

    def render(self, view):
        self.view = view
        return f"rendered {view.source}"


@pytest.fixture
def source(tmp_path):
    file = tmp_path / "a.md"
    file.write_text(TEXT, encoding="utf-8")
    return file


def build(source, chunk_text="alpha notes about retrieval", renderer=None):
    retriever = BM25Retriever()
    retriever.add([Chunk(id="c-0", source=str(source), text=chunk_text, position=0)])
    return SourcePageService(
        CatalogService(retriever),
        default_loaders(),
        renderer or FakeRenderer(),
        TermHighlighter(multilingual_tokenizer()),
    )


def test_marks_the_passage_of_a_chunk_inside_its_document(source):
    renderer = FakeRenderer()

    page = build(source, renderer=renderer).page(str(source), "c-0")

    assert page.content == f"rendered {source}"
    assert page.view.text == TEXT
    assert page.view.passage == "alpha notes\nabout retrieval"
    assert page.view is renderer.view


def test_highlights_the_given_terms_inside_the_passage(source):
    view = build(source).page(str(source), "c-0", terms="retrieval alpha").view

    marked = [(view.text[item.start : item.end], item.term) for item in view.highlights]
    assert marked == [("alpha", "alpha"), ("retrieval", "retrieval")]


def test_terms_outside_the_passage_are_not_highlighted(source):
    view = build(source).page(str(source), "c-0", terms="beta").view

    assert view.highlights == ()


def test_shows_the_whole_document_without_a_chunk(source):
    view = build(source).page(str(source)).view

    assert view.text == TEXT
    assert view.passage_start is None
    assert view.highlights == ()


def test_shows_the_whole_document_when_the_chunk_is_unknown_or_from_elsewhere(source):
    service = build(source)

    assert service.page(str(source), "gone").view.passage_start is None
    assert service.page(str(source), "").view.passage_start is None


def test_shows_the_whole_document_when_the_passage_is_no_longer_there(source):
    view = build(source, chunk_text="words that moved away").page(str(source), "c-0").view

    assert view.passage_start is None


def test_refuses_a_document_that_is_not_indexed(source, tmp_path):
    other = tmp_path / "secret.md"
    other.write_text("hidden", encoding="utf-8")

    with pytest.raises(LookupError):
        build(source).page(str(other))


def test_reports_a_document_no_loader_reads(tmp_path):
    source = tmp_path / "data.bin"
    source.write_bytes(b"\x00")

    with pytest.raises(UnsupportedFileError):
        build(source).page(str(source))


def test_reports_a_document_that_is_gone(source):
    service = build(source)
    source.unlink()

    with pytest.raises(OSError):
        service.page(str(source))


def test_supports_follows_the_renderer(source):
    assert build(source, renderer=FakeRenderer(True)).supports(str(source)) is True
    assert build(source, renderer=FakeRenderer(False)).supports(str(source)) is False


@pytest.mark.parametrize(
    "text, passage, span",
    [
        ("one two three", "two three", (4, 13)),
        ("one\n two \n three", "two three", (5, 16)),
        ("one two", "", None),
        ("one two", "   ", None),
        ("one two", "three", None),
        ("a (b) c", "(b) c", (2, 7)),
    ],
)
def test_passage_span_matches_across_whitespace(text, passage, span):
    assert passage_span(text, passage) == span
