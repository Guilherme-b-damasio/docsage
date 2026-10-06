import pytest

from docsage.domain.models import Document
from docsage.infrastructure.chunking import SlidingWindowChunker


def _doc(words: int) -> Document:
    return Document(source="a.txt", text=" ".join(f"w{i}" for i in range(words)))


def test_short_document_yields_single_chunk():
    chunks = SlidingWindowChunker(size=10, overlap=2).split(_doc(5))
    assert len(chunks) == 1
    assert chunks[0].text == "w0 w1 w2 w3 w4"


def test_windows_overlap():
    chunks = SlidingWindowChunker(size=4, overlap=2).split(_doc(8))
    assert [c.text.split()[0] for c in chunks] == ["w0", "w2", "w4"]
    assert chunks[-1].text.split()[-1] == "w7"


def test_chunk_ids_are_stable_and_unique():
    chunker = SlidingWindowChunker(size=3, overlap=1)
    first = [c.id for c in chunker.split(_doc(9))]
    second = [c.id for c in chunker.split(_doc(9))]
    assert first == second
    assert len(set(first)) == len(first)


def test_empty_document_yields_no_chunks():
    assert SlidingWindowChunker().split(Document(source="e.txt", text="")) == []


@pytest.mark.parametrize("size,overlap", [(0, 0), (5, 5), (5, -1)])
def test_invalid_configuration_is_rejected(size, overlap):
    with pytest.raises(ValueError):
        SlidingWindowChunker(size=size, overlap=overlap)
