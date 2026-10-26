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
from docsage.domain.models import Chunk, Document, Highlight, SourceFilter, TokenUsage
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


def test_indexing_stamps_each_chunk_with_the_time_its_document_was_indexed(tmp_path: Path):
    from datetime import UTC, datetime

    (tmp_path / "a.md").write_text("alpha beta gamma delta")
    retriever = BM25Retriever()
    clock = lambda: datetime(2026, 10, 22, 9, 30, 15, 123, tzinfo=UTC)  # noqa: E731
    service = IndexingService(
        [PlainTextLoader()],
        SlidingWindowChunker(size=2, overlap=0),
        retriever,
        InMemoryRepository(),
        clock=clock,
    )

    service.index([tmp_path / "a.md"])

    assert {chunk.indexed_at for chunk in retriever.chunks()} == {"2026-10-22T09:30:15+00:00"}


def test_unchanged_documents_keep_the_time_they_were_first_indexed(tmp_path: Path):
    from datetime import UTC, datetime, timedelta

    (tmp_path / "a.md").write_text("alpha")
    retriever = BM25Retriever()
    times = iter(datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=day) for day in range(3))
    service = IndexingService(
        [PlainTextLoader()],
        SlidingWindowChunker(),
        retriever,
        InMemoryRepository(),
        clock=lambda: next(times),
    )

    service.index([tmp_path / "a.md"])
    service.index([tmp_path / "a.md"])
    first = retriever.chunks()[0].indexed_at
    service.index([tmp_path / "a.md"], force=True)

    assert first == "2026-01-01T00:00:00+00:00"
    assert retriever.chunks()[0].indexed_at == "2026-01-02T00:00:00+00:00"


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


def _mixed_source_retriever():
    retriever = BM25Retriever()
    retriever.add(
        [
            Chunk(id="n#0", source="notes/alpha.md", text="alpha notes", position=0),
            Chunk(id="d#0", source="docs/alpha.md", text="alpha docs", position=0),
            Chunk(id="p#0", source="docs/alpha.pdf", text="alpha manual", position=0),
            Chunk(id="w#0", source="https://example.com/alpha", text="alpha page", position=0),
        ]
    )
    return retriever


def test_search_service_keeps_only_the_sources_the_filter_matches():
    service = SearchService(_mixed_source_retriever())

    results = service.search("alpha", top_k=5, source=SourceFilter("docs"))

    assert [result.chunk.source for result in results] == ["docs/alpha.md", "docs/alpha.pdf"]


def test_search_service_filters_by_file_type():
    service = SearchService(_mixed_source_retriever())

    results = service.search("alpha", top_k=5, source=SourceFilter(".md"))

    assert sorted(result.chunk.source for result in results) == ["docs/alpha.md", "notes/alpha.md"]


def test_search_service_returns_nothing_when_no_source_matches():
    service = SearchService(_mixed_source_retriever())

    assert service.search("alpha", top_k=5, source=SourceFilter("missing")) == []


class CountingRetriever(BM25Retriever):
    """Records the ``top_k`` each search asked the index for."""

    def __init__(self):
        super().__init__()
        self.asked = []

    def search(self, query, top_k):
        self.asked.append(top_k)
        return super().search(query, top_k)


def _chunks(source, count):
    return [
        Chunk(id=f"{source}#{index}", source=source, text="alpha", position=index)
        for index in range(count)
    ]


def test_search_service_asks_for_more_candidates_so_the_filter_can_keep_top_k():
    retriever = CountingRetriever()
    retriever.add(_chunks("a.md", 3) + _chunks("b.pdf", 9))

    results = SearchService(retriever).search("alpha", top_k=2, source=SourceFilter(".md"))

    assert retriever.asked == [8]
    assert len(results) == 2


def test_search_service_asks_only_for_top_k_without_a_filter():
    retriever = CountingRetriever()
    retriever.add(_chunks("a.md", 1))

    SearchService(retriever).search("alpha", top_k=2)

    assert retriever.asked == [2]


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


class RecordingSearchRenderer:
    def __init__(self):
        self.calls = []

    def render(self, query, results, source=None):
        sources = [result.chunk.source for result in results]
        self.calls.append((query, sources, source.pattern if source else ""))
        return f"<{query}: {len(results)}>"


def test_search_report_service_renders_the_ranked_results():
    from docsage.application.services import SearchReportService

    renderer = RecordingSearchRenderer()
    service = SearchReportService(SearchService(_alpha_beta_retriever()), renderer)

    assert service.report("  beta ", top_k=3) == "<beta: 1>"
    assert renderer.calls == [("beta", ["b.md"], "")]


def test_search_report_service_renders_a_blank_query_without_searching():
    from docsage.application.services import SearchReportService

    class FailingSearch:
        def search(self, query, top_k=5):
            raise AssertionError("must not search")

    renderer = RecordingSearchRenderer()

    assert SearchReportService(FailingSearch(), renderer).report("   ") == "<: 0>"


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


class FakeUrlLoader:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    def load(self, url):
        self.calls.append(url)
        page = self.pages[url]
        if isinstance(page, Exception):
            raise page
        return Document(source=url, text=page, metadata={"type": "html"})


def _url_service(pages, retriever=None, repository=None):
    loader = FakeUrlLoader(pages)
    service = IndexingService(
        [PlainTextLoader()],
        SlidingWindowChunker(),
        BM25Retriever() if retriever is None else retriever,
        repository or InMemoryRepository(),
        url_loader=loader,
    )
    return service, loader


def test_index_urls_stores_each_fetched_page_under_its_url():
    retriever = BM25Retriever()
    service, _ = _url_service({"https://x.io/a": "alpha page"}, retriever)

    report = service.index_urls(["https://x.io/a"])

    assert (report.documents, report.chunks, report.failed) == (1, 1, ())
    assert [chunk.source for chunk in retriever.chunks()] == ["https://x.io/a"]


def test_index_urls_reports_pages_that_fail_and_indexes_the_rest():
    repository = InMemoryRepository()
    service, _ = _url_service(
        {
            "https://x.io/down": OSError("connection refused"),
            "https://x.io/img": ValueError("Cannot index image/png content"),
            "https://x.io/ok": "fine",
        },
        repository=repository,
    )

    report = service.index_urls(["https://x.io/down", "https://x.io/img", "https://x.io/ok"])

    assert report.documents == 1
    assert report.failed == (
        ("https://x.io/down", "connection refused"),
        ("https://x.io/img", "Cannot index image/png content"),
    )
    assert repository.saved is not None


def test_index_urls_skips_unchanged_pages_unless_forced():
    service, _ = _url_service({"https://x.io/a": "alpha"})
    service.index_urls(["https://x.io/a"])

    assert service.index_urls(["https://x.io/a"]).unchanged == 1
    assert service.index_urls(["https://x.io/a"], force=True).documents == 1


def test_index_urls_without_a_url_loader_fails_every_url():
    service = IndexingService(
        [PlainTextLoader()], SlidingWindowChunker(), BM25Retriever(), InMemoryRepository()
    )

    report = service.index_urls(["https://x.io/a"])

    assert report.documents == 0
    assert report.failed == (("https://x.io/a", "Indexing web pages is not configured"),)


def test_remove_url_drops_the_page_and_the_pages_below_it():
    retriever = _indexed(
        "https://x.io/docs", "https://x.io/docs/setup", "https://x.io/docs-old", "docs/a.md"
    )

    report = RemovalService(retriever, InMemoryRepository()).remove_url("https://x.io/docs/")

    assert report.documents == ("https://x.io/docs/setup",)
    report = RemovalService(retriever, InMemoryRepository()).remove_url("https://x.io/docs")
    assert report.documents == ("https://x.io/docs",)
    assert sorted(chunk.source for chunk in retriever.chunks()) == [
        "docs/a.md",
        "https://x.io/docs-old",
    ]


def test_removing_a_path_never_drops_web_pages():
    retriever = _indexed("https://x.io/a")

    report = RemovalService(retriever, InMemoryRepository()).remove(Path("https:"))

    assert report.documents == ()
    assert len(retriever) == 1


def test_search_report_service_tells_the_renderer_which_sources_were_searched():
    from docsage.application.services import SearchReportService
    from docsage.domain.models import SourceFilter

    renderer = RecordingSearchRenderer()
    service = SearchReportService(SearchService(_alpha_beta_retriever()), renderer)

    service.report("beta", source=SourceFilter(".md"))
    service.report("   ", source=SourceFilter("docs"))

    assert renderer.calls == [("beta", ["b.md"], ".md"), ("", [], "docs")]


def test_search_report_service_returns_the_results_with_their_page():
    from docsage.application.services import SearchReportService

    renderer = RecordingSearchRenderer()
    service = SearchReportService(SearchService(_alpha_beta_retriever()), renderer)

    report = service.search("  beta ", top_k=3)

    assert report.query == "beta"
    assert [result.chunk.source for result in report.results] == ["b.md"]
    assert report.content == "<beta: 1>"


def test_question_answering_only_grounds_the_answer_on_the_filtered_sources():
    generator = FakeGenerator()
    service = QuestionAnsweringService(_mixed_source_retriever(), generator)

    answer = service.ask("alpha", top_k=5, source=SourceFilter("docs"))

    assert [result.chunk.source for result in answer.sources] == [
        "docs/alpha.md",
        "docs/alpha.pdf",
    ]
    assert [result.chunk.source for result in generator.calls[0][1]] == [
        "docs/alpha.md",
        "docs/alpha.pdf",
    ]


def test_answer_carries_the_source_filter_it_was_narrowed_to():
    service = QuestionAnsweringService(_mixed_source_retriever(), FakeGenerator())

    answer = service.ask("alpha", source=SourceFilter(".pdf"))

    assert answer.source == ".pdf"


def test_answer_over_the_whole_index_carries_no_source_filter():
    service = QuestionAnsweringService(_mixed_source_retriever(), FakeGenerator())

    assert service.ask("alpha").source == ""


def test_question_answering_skips_the_generator_when_the_filter_keeps_nothing():
    generator = FakeGenerator()
    service = QuestionAnsweringService(_mixed_source_retriever(), generator)

    answer = service.ask("alpha", source=SourceFilter("missing"))

    assert answer.sources == ()
    assert answer.source == "missing"
    assert generator.calls == []


def test_question_answering_asks_for_more_candidates_so_the_filter_can_keep_top_k():
    retriever = CountingRetriever()
    retriever.add(_chunks("a.md", 3) + _chunks("b.pdf", 9))

    answer = QuestionAnsweringService(retriever, FakeGenerator()).ask(
        "alpha", top_k=2, source=SourceFilter(".md")
    )

    assert retriever.asked == [8]
    assert len(answer.sources) == 2


def test_answer_report_service_narrows_the_answer_to_the_filtered_sources():
    from docsage.application.services import AnswerReportService

    class Renderer:
        def render(self, answer):
            return f"report for {answer.source}"

    service = AnswerReportService(
        QuestionAnsweringService(_mixed_source_retriever(), FakeGenerator()), Renderer()
    )

    report = service.report("alpha", top_k=5, source=SourceFilter("notes"))

    assert report.content == "report for notes"
    assert [result.chunk.source for result in report.answer.sources] == ["notes/alpha.md"]


def test_answer_comparison_service_answers_under_both_settings():
    from docsage.application.services import AnswerComparisonService, AnswerVariant

    rendered = []

    class Renderer:
        def render(self, comparison):
            rendered.append(comparison)
            return f"{comparison.left.label} vs {comparison.right.label}"

    retriever = _alpha_beta_retriever()
    left = AnswerVariant("top 1", QuestionAnsweringService(retriever, FakeGenerator()), 1)
    right = AnswerVariant("top 5", QuestionAnsweringService(retriever, FakeGenerator()), 5)

    report = AnswerComparisonService(left, right, Renderer()).compare("alpha beta")

    assert report.content == "top 1 vs top 5"
    assert rendered == [report.comparison]
    assert len(report.comparison.left.answer.sources) == 1
    assert len(report.comparison.right.answer.sources) == 2
    assert report.comparison.right.answer.text == "answer from 2 passages"


def test_answer_comparison_service_narrows_both_answers_to_the_same_sources():
    from docsage.application.services import AnswerComparisonService, AnswerVariant

    class Renderer:
        def render(self, comparison):
            return ""

    answering = QuestionAnsweringService(_mixed_source_retriever(), FakeGenerator())
    variants = (AnswerVariant("a", answering, 5), AnswerVariant("b", answering, 5))

    report = AnswerComparisonService(*variants, Renderer()).compare(
        "alpha", source=SourceFilter("notes")
    )

    for side in (report.comparison.left, report.comparison.right):
        assert side.answer.source == "notes"
        assert [result.chunk.source for result in side.answer.sources] == ["notes/alpha.md"]


def test_pdf_export_service_prints_the_rendered_dashboard():
    from docsage.application.services import PdfExportService

    class Dashboard:
        def render(self, top=15):
            return f"<html>top {top}</html>"

    class Printer:
        def __init__(self):
            self.pages = []

        def print_pdf(self, html):
            self.pages.append(html)
            return b"%PDF"

    printer = Printer()

    assert PdfExportService(Dashboard(), printer).export(top=4) == b"%PDF"
    assert printer.pages == ["<html>top 4</html>"]
