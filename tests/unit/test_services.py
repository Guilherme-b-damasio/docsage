from pathlib import Path

from docsage.application.services import (
    IndexingService,
    QuestionAnsweringService,
    RemovalReport,
    RemovalService,
    content_hash,
)
from docsage.domain.models import Chunk, Document
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


def test_reindexing_a_shrunk_file_drops_its_stale_chunks(tmp_path: Path):
    path = tmp_path / "notes.md"
    path.write_text("one two three four five six")
    retriever = BM25Retriever()
    service = IndexingService(
        [PlainTextLoader()],
        SlidingWindowChunker(size=2, overlap=0),
        retriever,
        InMemoryRepository(),
    )
    service.index([path])

    path.write_text("one two")
    service.index([path])

    assert [chunk.text for chunk in retriever.chunks()] == ["one two"]


class CountingChunker:
    def __init__(self):
        self.calls = 0
        self._inner = SlidingWindowChunker()

    def split(self, document):
        self.calls += 1
        return self._inner.split(document)


def _incremental_setup(tmp_path: Path):
    (tmp_path / "a.md").write_text("alpha")
    (tmp_path / "b.md").write_text("beta")
    chunker = CountingChunker()
    repository = InMemoryRepository()
    service = IndexingService([PlainTextLoader()], chunker, BM25Retriever(), repository)
    service.index(sorted(tmp_path.iterdir()))
    return service, chunker, repository


def test_reindexing_skips_unchanged_files(tmp_path: Path):
    service, chunker, repository = _incremental_setup(tmp_path)
    repository.saved = None

    report = service.index(sorted(tmp_path.iterdir()))

    assert (report.documents, report.unchanged) == (0, 2)
    assert chunker.calls == 2
    assert repository.saved is None


def test_reindexing_picks_up_modified_files(tmp_path: Path):
    service, chunker, repository = _incremental_setup(tmp_path)
    (tmp_path / "b.md").write_text("beta gamma")

    report = service.index(sorted(tmp_path.iterdir()))

    assert (report.documents, report.unchanged) == (1, 1)
    assert repository.saved.search("gamma", top_k=1)[0].chunk.source == str(tmp_path / "b.md")


def test_force_reindexes_unchanged_files(tmp_path: Path):
    service, chunker, _ = _incremental_setup(tmp_path)

    report = service.index(sorted(tmp_path.iterdir()), force=True)

    assert (report.documents, report.unchanged) == (2, 0)
    assert chunker.calls == 4


def test_indexed_chunks_carry_the_document_hash(tmp_path: Path):
    _, _, repository = _incremental_setup(tmp_path)
    hashes = {chunk.source: chunk.content_hash for chunk in repository.saved.chunks()}
    expected = content_hash(Document(source="", text="alpha"))
    assert hashes[str(tmp_path / "a.md")] == expected


def _indexed(*sources: str) -> BM25Retriever:
    retriever = BM25Retriever()
    retriever.add(
        Chunk(id=f"c{i}", source=source, text=f"text {i}", position=0)
        for i, source in enumerate(sources)
    )
    return retriever


def test_removal_drops_a_single_file():
    retriever = _indexed(str(Path("docs/a.md")), str(Path("docs/b.md")))
    repository = InMemoryRepository()

    report = RemovalService(retriever, repository).remove(Path("docs/a.md"))

    assert report.documents == (str(Path("docs/a.md")),)
    assert report.chunks == 1
    assert [chunk.source for chunk in retriever.chunks()] == [str(Path("docs/b.md"))]
    assert repository.saved is retriever


def test_removal_of_a_folder_drops_everything_under_it():
    retriever = _indexed(
        str(Path("docs/a.md")), str(Path("docs/sub/b.md")), str(Path("docs-old/c.md"))
    )

    report = RemovalService(retriever, InMemoryRepository()).remove(Path("docs"))

    assert report.documents == (str(Path("docs/a.md")), str(Path("docs/sub/b.md")))
    assert len(retriever) == 1


def test_removal_without_matches_does_not_save():
    repository = InMemoryRepository()
    report = RemovalService(_indexed("a.md"), repository).remove(Path("other.md"))
    assert report == RemovalReport((), 0)
    assert repository.saved is None


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

