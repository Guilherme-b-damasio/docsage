from pathlib import Path

from docsage.application.services import IndexingService, QuestionAnsweringService
from docsage.domain.models import Document
from docsage.infrastructure.bm25 import BM25Retriever
from docsage.infrastructure.chunking import SlidingWindowChunker
from docsage.infrastructure.loaders import PlainTextLoader


class InMemoryRepository:
    def __init__(self):
        self.saved = None

    def save(self, retriever):
        self.saved = retriever

    def load(self):
        return self.saved or BM25Retriever()


class FakeGenerator:
    def __init__(self):
        self.calls = []

    def generate(self, question, context):
        self.calls.append((question, list(context)))
        return f"answer from {len(context)} passages"


def test_indexing_skips_unsupported_files(tmp_path: Path):
    (tmp_path / "notes.md").write_text("RAG combines retrieval and generation.")
    (tmp_path / "image.png").write_bytes(b"\x89PNG")
    repository = InMemoryRepository()
    service = IndexingService(
        [PlainTextLoader()], SlidingWindowChunker(), BM25Retriever(), repository
    )

    report = service.index(sorted(tmp_path.iterdir()))

    assert (report.documents, report.chunks) == (1, 1)
    assert report.skipped == (str(tmp_path / "image.png"),)
    assert repository.saved is not None


def test_question_answering_passes_retrieved_context_to_generator():
    retriever = BM25Retriever()
    document = Document(source="doc.txt", text="Paris is the capital of France.")
    retriever.add(SlidingWindowChunker().split(document))
    generator = FakeGenerator()

    answer = QuestionAnsweringService(retriever, generator).ask("capital of France?")

    assert answer.text == "answer from 1 passages"
    assert generator.calls[0][0] == "capital of France?"


def test_question_answering_without_context_skips_generator():
    generator = FakeGenerator()
    answer = QuestionAnsweringService(BM25Retriever(), generator).ask("anything")
    assert answer.sources == ()
    assert generator.calls == []

