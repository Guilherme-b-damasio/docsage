import pytest

from docsage.domain.models import Chunk, Document
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
