from pathlib import Path

from docsage.domain.models import Chunk, Highlight, SearchResult
from docsage.infrastructure.source_links import (
    FileAndUrlLocator,
    HighlightingLocator,
    ServedSourceLocator,
    passage_href,
)


def _chunk(source, first_page=None):
    return Chunk(id=f"{source}#0", source=source, text="text", position=0, first_page=first_page)


def test_web_pages_link_to_their_url():
    url = "https://example.com/guide?x=1"

    assert FileAndUrlLocator().href(_chunk(url)) == url


def test_absolute_files_link_to_a_file_uri(tmp_path):
    source = tmp_path / "notes.md"

    assert FileAndUrlLocator().href(_chunk(str(source))) == source.resolve().as_uri()


def test_relative_files_resolve_from_the_base(tmp_path):
    href = FileAndUrlLocator(tmp_path).href(_chunk("docs/notes.md"))

    assert href == (tmp_path / "docs" / "notes.md").resolve().as_uri()


def test_relative_files_resolve_from_the_working_directory_by_default():
    href = FileAndUrlLocator().href(_chunk("notes.md"))

    assert href == (Path.cwd() / "notes.md").resolve().as_uri()


def test_pdf_passages_open_at_their_first_page(tmp_path):
    href = FileAndUrlLocator(tmp_path).href(_chunk("guide.pdf", first_page=3))

    assert href == (tmp_path / "guide.pdf").resolve().as_uri() + "#page=3"


def test_served_files_link_to_the_endpoint_with_the_source_quoted():
    locator = ServedSourceLocator("/ui/source")

    assert locator.href(_chunk("docs/a b&c.md")) == "/ui/source?path=docs%2Fa%20b%26c.md"
    assert locator.href(_chunk("guide.pdf", first_page=3)) == "/ui/source?path=guide.pdf#page=3"
    assert locator.href(_chunk("https://example.com/x")) == "https://example.com/x"


def _result(source, text, highlights=()):
    chunk = Chunk(id=f"{source}#0", source=source, text=text, position=0)
    return SearchResult(chunk, 1.0, tuple(highlights))


def test_short_passages_are_quoted_whole(tmp_path):
    locator = HighlightingLocator(FileAndUrlLocator(tmp_path))

    href = locator.passage_href(_result("a.md", "Chunks are stored as JSON."))

    base = (tmp_path / "a.md").resolve().as_uri()
    assert href == f"{base}#:~:text=Chunks%20are%20stored%20as%20JSON."


def test_long_passages_point_at_their_first_and_last_words(tmp_path):
    text = " ".join(f"word{number}" for number in range(1, 16))
    locator = HighlightingLocator(FileAndUrlLocator(tmp_path))

    fragment = locator.passage_href(_result("a.md", text)).split("#:~:")[1]

    assert fragment == (
        "text=word1%20word2%20word3%20word4%20word5%20word6,"
        "word10%20word11%20word12%20word13%20word14%20word15"
    )


def test_matched_terms_are_highlighted_after_the_passage(tmp_path):
    text = "The index keeps chunks."
    highlights = [Highlight(4, 9, "index"), Highlight(16, 22, "chunk")]
    locator = HighlightingLocator(FileAndUrlLocator(tmp_path))

    fragment = locator.passage_href(_result("a.md", text, highlights)).split("#:~:")[1]

    assert fragment.split("&")[1:] == ["text=index", "text=chunks"]


def test_at_most_four_terms_are_highlighted(tmp_path):
    text = "one two three four five six"
    highlights = [Highlight(start, start + 3, "x") for start in (0, 4, 8, 14, 19)]
    locator = HighlightingLocator(FileAndUrlLocator(tmp_path))

    fragment = locator.passage_href(_result("a.md", text, highlights)).split("#:~:")[1]

    assert len(fragment.split("&")) == 5


def test_hyphens_and_commas_in_the_passage_are_encoded(tmp_path):
    locator = HighlightingLocator(FileAndUrlLocator(tmp_path))

    href = locator.passage_href(_result("a.md", "re-index, then search"))

    assert href.endswith("#:~:text=re%2Dindex%2C%20then%20search")


def test_web_pages_open_at_the_passage():
    locator = HighlightingLocator(FileAndUrlLocator())

    href = locator.passage_href(_result("https://example.com/guide", "Alpha notes here."))

    assert href == "https://example.com/guide#:~:text=Alpha%20notes%20here."


def test_formats_a_browser_cannot_point_into_keep_their_link(tmp_path):
    locator = HighlightingLocator(FileAndUrlLocator(tmp_path))

    assert locator.passage_href(_result("guide.pdf", "Alpha notes.")) == (
        tmp_path / "guide.pdf"
    ).resolve().as_uri()
    assert locator.passage_href(_result("notes.docx", "Alpha notes.")) == (
        tmp_path / "notes.docx"
    ).resolve().as_uri()


def test_links_that_already_carry_a_fragment_are_left_alone():
    locator = HighlightingLocator(ServedSourceLocator("/ui/source"))
    chunk = Chunk(id="g#0", source="guide.pdf", text="Alpha.", position=0, first_page=2)

    assert locator.passage_href(SearchResult(chunk, 1.0)) == "/ui/source?path=guide.pdf#page=2"


def test_an_empty_passage_keeps_the_plain_link(tmp_path):
    locator = HighlightingLocator(FileAndUrlLocator(tmp_path))

    assert locator.passage_href(_result("a.md", "   ")) == (
        tmp_path / "a.md"
    ).resolve().as_uri()


def test_chunk_links_are_untouched_by_the_decorator(tmp_path):
    inner = FileAndUrlLocator(tmp_path)
    chunk = Chunk(id="a#0", source="a.md", text="Alpha.", position=0)

    assert HighlightingLocator(inner).href(chunk) == inner.href(chunk)


def test_passage_href_falls_back_to_the_plain_link(tmp_path):
    result = _result("a.md", "Alpha notes.")
    plain = FileAndUrlLocator(tmp_path)

    assert passage_href(plain, result) == plain.href(result.chunk)
    assert passage_href(HighlightingLocator(plain), result) == HighlightingLocator(
        plain
    ).passage_href(result)
