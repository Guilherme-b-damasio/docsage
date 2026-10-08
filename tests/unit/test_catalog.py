from docsage.application.services import CatalogService, DocumentSummary
from docsage.domain.models import Chunk
from docsage.infrastructure.bm25 import BM25Retriever


def catalog(chunks):
    retriever = BM25Retriever()
    retriever.add(chunks)
    return CatalogService(retriever)


CHUNKS = [
    Chunk(id="n-1", source="notes.md", text="Run pip install.", position=1, section="Setup"),
    Chunk(id="n-0", source="notes.md", text="Intro text.", position=0, section="Intro"),
    Chunk(id="n-2", source="notes.md", text="More setup.", position=2, section="Setup"),
    Chunk(id="g-0", source="guide.pdf", text="Page one.", position=0, first_page=1, last_page=2),
    Chunk(id="g-1", source="guide.pdf", text="Page five.", position=1, first_page=5, last_page=5),
    Chunk(id="t-0", source="a.txt", text="Plain.", position=0),
]


def test_documents_are_summarized_and_sorted_by_source():
    documents = catalog(CHUNKS).documents()

    assert documents == [
        DocumentSummary("a.txt", ("t-0",), pages=None, sections=()),
        DocumentSummary("guide.pdf", ("g-0", "g-1"), pages=5, sections=()),
        DocumentSummary("notes.md", ("n-0", "n-1", "n-2"), pages=None, sections=("Intro", "Setup")),
    ]
    assert documents[2].chunks == 3


def test_documents_of_an_empty_index():
    assert catalog([]).documents() == []


def test_document_chunks_are_in_reading_order():
    chunks = catalog(CHUNKS).document_chunks("notes.md")

    assert [chunk.id for chunk in chunks] == ["n-0", "n-1", "n-2"]
    assert catalog(CHUNKS).document_chunks("missing.md") == []


def test_chunk_by_id():
    service = catalog(CHUNKS)

    assert service.chunk("g-1").text == "Page five."
    assert service.chunk("nope") is None
