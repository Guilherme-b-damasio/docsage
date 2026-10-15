import logging
from pathlib import Path

from docsage.application.services import (
    IndexingService,
    QuestionAnsweringService,
    RemovalReport,
    RemovalService,
    SearchService,
    content_hash,
)
from docsage.domain.models import Chunk, Document, Highlight, TokenUsage
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



def test_indexing_logs_each_document_and_a_summary(tmp_path: Path, caplog):
    (tmp_path / "notes.md").write_text("RAG combines retrieval and generation.")
    (tmp_path / "image.png").write_bytes(b"\x89PNG")
    service = IndexingService(
        [PlainTextLoader()], SlidingWindowChunker(), BM25Retriever(), InMemoryRepository()
    )
    caplog.set_level(logging.DEBUG, logger="docsage")

    service.index(sorted(tmp_path.iterdir()))

    events = {record.getMessage(): record for record in caplog.records}
    assert events["indexed document"].source == str(tmp_path / "notes.md")
    assert events["skipped unsupported file"].path == str(tmp_path / "image.png")
    summary = events["indexing finished"]
    assert (summary.documents, summary.chunks, summary.skipped) == (1, 1, 1)


def test_question_answering_logs_retrieval(caplog):
    caplog.set_level(logging.DEBUG, logger="docsage")
    QuestionAnsweringService(BM25Retriever(), FakeGenerator()).ask("anything", top_k=3)
    record = next(r for r in caplog.records if r.getMessage() == "retrieved context")
    assert (record.top_k, record.results) == (3, 0)


def test_search_service_ranks_chunks_from_the_retriever():
    retriever = BM25Retriever()
    retriever.add(
        [
            Chunk(id="a#0", source="a.md", text="alpha notes", position=0),
            Chunk(id="b#0", source="b.md", text="beta notes", position=0),
        ]
    )

    results = SearchService(retriever).search("beta", top_k=3)

    assert [result.chunk.source for result in results] == ["b.md"]


class FakeHighlighter:
    def __init__(self):
        self.calls = []

    def highlight(self, query, text):
        self.calls.append((query, text))
        return [Highlight(0, 4, query)]


def _alpha_beta_retriever():
    retriever = BM25Retriever()
    retriever.add(
        [
            Chunk(id="a#0", source="a.md", text="alpha notes", position=0),
            Chunk(id="b#0", source="b.md", text="beta notes", position=0),
        ]
    )
    return retriever


def test_search_service_attaches_highlights_to_each_result():
    highlighter = FakeHighlighter()

    results = SearchService(_alpha_beta_retriever(), highlighter).search("beta", top_k=3)

    assert [result.highlights for result in results] == [(Highlight(0, 4, "beta"),)]
    assert highlighter.calls == [("beta", "beta notes")]


def test_search_service_without_highlighter_leaves_results_bare():
    results = SearchService(_alpha_beta_retriever()).search("beta", top_k=3)

    assert results[0].highlights == ()


def test_question_answering_highlights_sources_and_passes_them_on():
    generator = FakeGenerator()
    service = QuestionAnsweringService(_alpha_beta_retriever(), generator, FakeHighlighter())

    answer = service.ask("alpha")

    assert answer.sources[0].matched_terms == ("alpha",)
    assert generator.calls[0][1][0].highlights == (Highlight(0, 4, "alpha"),)


def test_answer_report_service_renders_the_answer():
    from docsage.application.services import AnswerReportService

    retriever = BM25Retriever()
    retriever.add([Chunk("a#0", "a.md", "Paris is in France.", 0)])
    rendered = []

    class Renderer:
        def render(self, answer):
            rendered.append(answer)
            return f"<{answer.text}>"

    service = AnswerReportService(QuestionAnsweringService(retriever, FakeGenerator()), Renderer())
    report = service.report("Where is Paris?", top_k=3)

    assert report.content == "<answer from 1 passages>"
    assert rendered == [report.answer]
    assert report.answer.sources[0].chunk.source == "a.md"


class FakeStreamingGenerator(FakeGenerator):
    def stream(self, question, context):
        self.calls.append((question, list(context)))
        yield "answer "
        yield "in pieces"


def test_question_answering_streams_pieces_to_the_callback():
    retriever = BM25Retriever()
    retriever.add([Chunk(id="c", source="a.md", text="alpha beta", position=0)])
    pieces = []

    answer = QuestionAnsweringService(retriever, FakeStreamingGenerator()).ask(
        "alpha", on_text=pieces.append
    )

    assert pieces == ["answer ", "in pieces"]
    assert answer.text == "answer in pieces"


def test_question_answering_sends_a_whole_answer_when_the_generator_cannot_stream():
    retriever = BM25Retriever()
    retriever.add([Chunk(id="c", source="a.md", text="alpha beta", position=0)])
    pieces: list[str] = []
    service = QuestionAnsweringService(retriever, FakeGenerator())

    answer = service.ask("alpha", on_text=pieces.append)

    assert pieces == [answer.text] == ["answer from 1 passages"]


def test_question_answering_without_context_still_reports_text():
    pieces = []

    QuestionAnsweringService(BM25Retriever(), FakeStreamingGenerator()).ask(
        "anything", on_text=pieces.append
    )

    assert pieces == ["No relevant context found in the index."]


class UsageReportingFakeGenerator(FakeGenerator):
    def __init__(self, usage):
        super().__init__()
        self.last_usage = None
        self._usage = usage

    def generate(self, question, context):
        text = super().generate(question, context)
        self.last_usage = self._usage
        return text


class FixedCostEstimator:
    def __init__(self):
        self.priced = []

    def estimate(self, usage):
        self.priced.append(usage)
        return 0.25


def _capital_retriever() -> BM25Retriever:
    retriever = BM25Retriever()
    document = Document(source="doc.txt", text="Paris is the capital of France.")
    retriever.add(SlidingWindowChunker().split(document))
    return retriever


def test_answers_carry_the_token_usage_and_its_cost():
    usage = TokenUsage(model="m", input_tokens=100, output_tokens=20)
    estimator = FixedCostEstimator()
    service = QuestionAnsweringService(
        _capital_retriever(), UsageReportingFakeGenerator(usage), cost_estimator=estimator
    )

    answer = service.ask("capital of France?")

    assert (answer.usage, answer.cost_usd) == (usage, 0.25)
    assert estimator.priced == [usage]


def test_usage_without_an_estimator_has_no_cost():
    usage = TokenUsage(model="m", input_tokens=100, output_tokens=20)
    service = QuestionAnsweringService(_capital_retriever(), UsageReportingFakeGenerator(usage))

    answer = service.ask("capital of France?")

    assert (answer.usage, answer.cost_usd) == (usage, None)


def test_generators_that_do_not_report_usage_leave_it_empty():
    answer = QuestionAnsweringService(
        _capital_retriever(), FakeGenerator(), cost_estimator=FixedCostEstimator()
    ).ask("capital of France?")

    assert (answer.usage, answer.cost_usd) == (None, None)


def test_answers_without_context_cost_nothing():
    estimator = FixedCostEstimator()
    usage = TokenUsage(model="m", input_tokens=1, output_tokens=1)
    answer = QuestionAnsweringService(
        BM25Retriever(), UsageReportingFakeGenerator(usage), cost_estimator=estimator
    ).ask("anything")

    assert answer.usage is None
    assert estimator.priced == []
