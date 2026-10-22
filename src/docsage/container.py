"""Composition root: the only place that knows which adapters implement which ports."""

from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from docsage.application.services import (
    AnswerReportService,
    CatalogService,
    ChatService,
    DashboardService,
    EvaluationService,
    IndexingService,
    LiveWatchService,
    QuestionAnsweringService,
    RelationService,
    RemovalService,
    SearchReportService,
    SearchService,
    StatsService,
    WatchService,
)
from docsage.domain.models import ANSWER_LENGTHS, AnswerStyle
from docsage.domain.ports import (
    AnswerGenerator,
    AnswerRenderer,
    Chunker,
    ConversationalAnswerGenerator,
    DashboardRenderer,
    Embedder,
    EvaluationRenderer,
    FileWatcher,
    Reranker,
    Retriever,
    UrlLoader,
)
from docsage.infrastructure.bm25 import BM25Retriever, JsonIndexRepository
from docsage.infrastructure.chunking import (
    ChunkerByType,
    MarkdownChunker,
    SentenceChunker,
    SlidingWindowChunker,
)
from docsage.infrastructure.config import ConfigError, read_config
from docsage.infrastructure.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    CachedEmbedder,
    EmbeddingRetriever,
    SentenceTransformerEmbedder,
)
from docsage.infrastructure.evaluation_report import (
    HtmlEvaluationRenderer,
    TextEvaluationRenderer,
)
from docsage.infrastructure.fusion import ReciprocalRankFusionRetriever
from docsage.infrastructure.highlighting import TermHighlighter
from docsage.infrastructure.html_dashboard import HtmlDashboardRenderer
from docsage.infrastructure.html_report import HtmlAnswerRenderer
from docsage.infrastructure.html_search import HtmlSearchRenderer, PageLinks
from docsage.infrastructure.loaders import default_loaders
from docsage.infrastructure.markdown_report import MarkdownAnswerRenderer
from docsage.infrastructure.mermaid import MermaidDashboardRenderer
from docsage.infrastructure.pricing import PriceTable
from docsage.infrastructure.projection import PcaProjector
from docsage.infrastructure.reranking import RerankingRetriever
from docsage.infrastructure.source_links import ServedSourceLocator
from docsage.infrastructure.text_dashboard import TextDashboardRenderer
from docsage.infrastructure.text_report import TextAnswerRenderer
from docsage.infrastructure.tokenizer import multilingual_tokenizer
from docsage.infrastructure.watching import PollingWatcher
from docsage.infrastructure.web_loader import WebPageLoader

DEFAULT_INDEX_PATH = Path(".docsage") / "index.json"

REPORT_FORMATS: dict[str, type[AnswerRenderer]] = {
    "html": HtmlAnswerRenderer,
    "markdown": MarkdownAnswerRenderer,
    "text": TextAnswerRenderer,
}

CHUNKERS: dict[str, type[SlidingWindowChunker | SentenceChunker]] = {
    "window": SlidingWindowChunker,
    "sentence": SentenceChunker,
}
"""How plain text (and each Markdown section) is cut into chunks of ``chunk_size`` words."""

RETRIEVERS = ("bm25", "embedding", "hybrid")
"""Ranking strategies; every one rebuilds from the same stored chunks."""

EMBEDDING_RETRIEVERS = ("embedding", "hybrid")
"""Strategies that embed chunks, so the dashboard can also map them."""

DASHBOARD_FORMATS: dict[str, type[DashboardRenderer]] = {
    "html": HtmlDashboardRenderer,
    "text": TextDashboardRenderer,
    "mermaid": MermaidDashboardRenderer,
}

EVALUATION_FORMATS: dict[str, type[EvaluationRenderer]] = {
    "html": HtmlEvaluationRenderer,
    "text": TextEvaluationRenderer,
}


@dataclass(frozen=True)
class Settings:
    index_path: Path = DEFAULT_INDEX_PATH
    chunk_size: int = 200
    chunk_overlap: int = 40
    chunker: str = "window"
    model: str | None = None
    retriever: str = "bm25"
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    rerank: bool = False
    """Let Claude reorder the retriever's best candidates for ``search`` and ``ask``."""
    rerank_candidates: int = 20
    prompt_cache: bool = True
    """Cache the passages sent to Claude so follow-ups on the same context cost less."""
    chat_history_turns: int = 10
    """How many earlier turns ``chat`` sends with each question."""
    answer_language: str = ""
    """Language Claude answers in; empty means the language of the question."""
    answer_length: str = "medium"
    """One of ``ANSWER_LENGTHS``: short, medium (the model decides) or long."""

    @property
    def answer_style(self) -> AnswerStyle:
        return AnswerStyle(self.answer_language, self.answer_length)


def load_settings(config_path: Path | None = None, **overrides: Any) -> Settings:
    """Builds settings from defaults, then the config file, then non-None overrides."""
    values = read_config(config_path) if config_path else {}
    values.update({key: value for key, value in overrides.items() if value is not None})
    settings = replace(Settings(), **values)
    if settings.rerank_candidates < 1:
        raise ConfigError("rerank_candidates must be at least 1")
    if settings.chat_history_turns < 0:
        raise ConfigError("chat_history_turns must not be negative")
    if settings.answer_length not in ANSWER_LENGTHS:
        raise ConfigError(
            f"Unknown answer length: {settings.answer_length} "
            f"(choose from {', '.join(ANSWER_LENGTHS)})"
        )
    if settings.chunker not in CHUNKERS:
        raise ConfigError(
            f"Unknown chunker: {settings.chunker} (choose from {', '.join(CHUNKERS)})"
        )
    if settings.retriever not in RETRIEVERS:
        raise ConfigError(
            f"Unknown retriever: {settings.retriever} (choose from {', '.join(RETRIEVERS)})"
        )
    return settings


class Container:
    def __init__(
        self,
        settings: Settings,
        generator: AnswerGenerator | None = None,
        embedder: Embedder | None = None,
        reranker: Reranker | None = None,
        url_loader: UrlLoader | None = None,
        watcher: FileWatcher | None = None,
    ) -> None:
        """``generator``, ``embedder``, ``reranker``, ``url_loader`` and ``watcher`` replace
        the Claude adapters, the local embedding model, the web fetcher and the folder
        poller, e.g. with offline fakes in tests."""
        self._settings = settings
        self._generator = generator
        self._embedder = embedder
        self._reranker = reranker
        self._url_loader = url_loader
        self._watcher = watcher
        self._tokenizer = multilingual_tokenizer()
        self._highlighter = TermHighlighter(self._tokenizer)
        self._repository = JsonIndexRepository(settings.index_path, self._new_retriever)

    def _new_retriever(self) -> Retriever:
        if self._settings.retriever == "embedding":
            return EmbeddingRetriever(self._cached_embedder())
        if self._settings.retriever == "hybrid":
            return ReciprocalRankFusionRetriever(
                [
                    BM25Retriever(tokenizer=self._tokenizer),
                    EmbeddingRetriever(self._cached_embedder()),
                ]
            )
        return BM25Retriever(tokenizer=self._tokenizer)

    def _ranking_retriever(self) -> Retriever:
        """The stored index, behind the reranker when ``rerank`` is on."""
        retriever = self._repository.load()
        if not self._settings.rerank:
            return retriever
        return RerankingRetriever(
            retriever, self._claude_reranker(), self._settings.rerank_candidates
        )

    def _claude_reranker(self) -> Reranker:
        if self._reranker is not None:
            return self._reranker
        # Imported lazily so commands that never call the API don't need credentials.
        from docsage.infrastructure.claude_reranker import ClaudeReranker

        if self._settings.model:
            return ClaudeReranker(model=self._settings.model)
        return ClaudeReranker()

    def _cached_embedder(self) -> Embedder:
        model = self._settings.embedding_model
        inner = self._embedder or SentenceTransformerEmbedder(model)
        index_path = self._settings.index_path
        cache_path = index_path.with_name(f"{index_path.stem}.embeddings.json")
        return CachedEmbedder(inner, cache_path, model)

    def indexing_service(self) -> IndexingService:
        return self._indexing_service(self._repository.load())

    def _indexing_service(self, retriever: Retriever) -> IndexingService:
        return IndexingService(
            loaders=default_loaders(),
            chunker=self._chunker(),
            retriever=retriever,
            repository=self._repository,
            url_loader=self._url_loader or WebPageLoader(),
        )

    def watch_service(self, interval: float = 1.0) -> WatchService:
        """Polls every ``interval`` seconds, never looking inside the index's own folder."""
        return self._watch_service(self._file_watcher(interval))

    def live_watch_service(
        self, interval: float = 1.0, guard: AbstractContextManager[object] | None = None
    ) -> LiveWatchService:
        """Like ``watch_service``, but reloads the index for every batch and applies it
        inside ``guard``, for watching while other writers (MCP tools) share the index."""
        watcher = self._file_watcher(interval)
        return LiveWatchService(watcher, lambda: self._watch_service(watcher), guard)

    def _file_watcher(self, interval: float) -> FileWatcher:
        return self._watcher or PollingWatcher(interval, ignore=[self._settings.index_path.parent])

    def _watch_service(self, watcher: FileWatcher) -> WatchService:
        retriever = self._repository.load()
        return WatchService(
            self._indexing_service(retriever),
            RemovalService(retriever, self._repository),
            watcher,
        )

    def _chunker(self) -> Chunker:
        settings = self._settings
        body = CHUNKERS[settings.chunker](settings.chunk_size, settings.chunk_overlap)
        # HTML pages and Word documents are loaded with their headings as Markdown lines,
        # so all three split alike.
        by_headings = MarkdownChunker(body)
        return ChunkerByType(
            {kind: by_headings for kind in ("markdown", "html", "docx")}, default=body
        )

    def removal_service(self) -> RemovalService:
        return RemovalService(self._repository.load(), self._repository)

    def stats_service(self) -> StatsService:
        return StatsService(self._repository.load(), self._tokenizer, self._repository)

    def dashboard_service(self, dashboard_format: str = "html") -> DashboardService:
        """``dashboard_format`` is a key of ``DASHBOARD_FORMATS``."""
        try:
            renderer = DASHBOARD_FORMATS[dashboard_format]()
        except KeyError:
            raise ValueError(f"Unknown dashboard format: {dashboard_format}") from None
        retriever = self._repository.load()
        stats = StatsService(retriever, self._tokenizer, self._repository)
        relations = RelationService(retriever, self._tokenizer)
        projector = None
        if self._settings.retriever in EMBEDDING_RETRIEVERS:
            projector = PcaProjector(self._cached_embedder())
        return DashboardService(stats, retriever, renderer, relations, projector)

    def question_answering_service(self) -> QuestionAnsweringService:
        return QuestionAnsweringService(
            self._ranking_retriever(),
            self._answer_generator(),
            self._highlighter,
            PriceTable(),
        )

    def chat_service(self) -> ChatService:
        """A new conversation; it remembers its turns for as long as the service lives."""
        return ChatService(
            self._ranking_retriever(),
            self._conversational_generator(),
            self._highlighter,
            self._settings.chat_history_turns,
            PriceTable(),
        )

    def _conversational_generator(self) -> ConversationalAnswerGenerator:
        generator = self._answer_generator()
        if not isinstance(generator, ConversationalAnswerGenerator):
            raise TypeError(f"{type(generator).__name__} cannot hold a conversation")
        return generator

    def answer_report_service(
        self, report_format: str = "html", source_endpoint: str | None = None
    ) -> AnswerReportService:
        """``report_format`` is a key of ``REPORT_FORMATS``. With ``source_endpoint`` the HTML
        report links cited files to where a web server serves them instead of ``file://``."""
        try:
            renderer = REPORT_FORMATS[report_format]()
        except KeyError:
            raise ValueError(f"Unknown report format: {report_format}") from None
        if source_endpoint is not None and report_format == "html":
            renderer = HtmlAnswerRenderer(ServedSourceLocator(source_endpoint))
        return AnswerReportService(self.question_answering_service(), renderer)

    def _answer_generator(self) -> AnswerGenerator:
        if self._generator is not None:
            return self._generator
        # Imported lazily so commands that never call the API don't need credentials.
        from docsage.infrastructure.claude_generator import ClaudeAnswerGenerator

        options: dict[str, Any] = {
            "cache_context": self._settings.prompt_cache,
            "style": self._settings.answer_style,
        }
        if self._settings.model:
            options["model"] = self._settings.model
        return ClaudeAnswerGenerator(**options)

    def catalog_service(self) -> CatalogService:
        return CatalogService(self._repository.load())

    def evaluation_service(self, evaluation_format: str = "text") -> EvaluationService:
        """Evaluates the configured retriever (and reranker, when on) as ``search`` uses it.

        ``evaluation_format`` is a key of ``EVALUATION_FORMATS``.
        """
        try:
            renderer = EVALUATION_FORMATS[evaluation_format]()
        except KeyError:
            raise ValueError(f"Unknown evaluation format: {evaluation_format}") from None
        return EvaluationService(self._ranking_retriever(), renderer)

    def search_service(self) -> SearchService:
        return SearchService(self._ranking_retriever(), self._highlighter)

    def search_report_service(self, links: PageLinks | None = None) -> SearchReportService:
        """Renders search results as an HTML page; ``links`` add the web UI's form."""
        locator = ServedSourceLocator(links.source) if links and links.source else None
        return SearchReportService(self.search_service(), HtmlSearchRenderer(links, locator))
