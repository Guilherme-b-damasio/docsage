"""Composition root: the only place that knows which adapters implement which ports."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from docsage.application.services import (
    AnswerReportService,
    CatalogService,
    DashboardService,
    IndexingService,
    QuestionAnsweringService,
    RelationService,
    RemovalService,
    SearchService,
    StatsService,
)
from docsage.domain.ports import (
    AnswerGenerator,
    AnswerRenderer,
    Chunker,
    DashboardRenderer,
    Embedder,
    Reranker,
    Retriever,
)
from docsage.infrastructure.bm25 import BM25Retriever, JsonIndexRepository
from docsage.infrastructure.chunking import ChunkerByType, MarkdownChunker, SlidingWindowChunker
from docsage.infrastructure.config import ConfigError, read_config
from docsage.infrastructure.embeddings import (
    DEFAULT_EMBEDDING_MODEL,
    CachedEmbedder,
    EmbeddingRetriever,
    SentenceTransformerEmbedder,
)
from docsage.infrastructure.fusion import ReciprocalRankFusionRetriever
from docsage.infrastructure.highlighting import TermHighlighter
from docsage.infrastructure.html_dashboard import HtmlDashboardRenderer
from docsage.infrastructure.html_report import HtmlAnswerRenderer
from docsage.infrastructure.loaders import default_loaders
from docsage.infrastructure.mermaid import MermaidDashboardRenderer
from docsage.infrastructure.reranking import RerankingRetriever
from docsage.infrastructure.text_dashboard import TextDashboardRenderer
from docsage.infrastructure.text_report import TextAnswerRenderer
from docsage.infrastructure.tokenizer import multilingual_tokenizer

DEFAULT_INDEX_PATH = Path(".docsage") / "index.json"

REPORT_FORMATS: dict[str, type[AnswerRenderer]] = {
    "html": HtmlAnswerRenderer,
    "text": TextAnswerRenderer,
}

RETRIEVERS = ("bm25", "embedding", "hybrid")
"""Ranking strategies; every one rebuilds from the same stored chunks."""

DASHBOARD_FORMATS: dict[str, type[DashboardRenderer]] = {
    "html": HtmlDashboardRenderer,
    "text": TextDashboardRenderer,
    "mermaid": MermaidDashboardRenderer,
}


@dataclass(frozen=True)
class Settings:
    index_path: Path = DEFAULT_INDEX_PATH
    chunk_size: int = 200
    chunk_overlap: int = 40
    model: str | None = None
    retriever: str = "bm25"
    embedding_model: str = DEFAULT_EMBEDDING_MODEL
    rerank: bool = False
    """Let Claude reorder the retriever's best candidates for ``search`` and ``ask``."""
    rerank_candidates: int = 20


def load_settings(config_path: Path | None = None, **overrides: Any) -> Settings:
    """Builds settings from defaults, then the config file, then non-None overrides."""
    values = read_config(config_path) if config_path else {}
    values.update({key: value for key, value in overrides.items() if value is not None})
    settings = replace(Settings(), **values)
    if settings.rerank_candidates < 1:
        raise ConfigError("rerank_candidates must be at least 1")
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
    ) -> None:
        """``generator``, ``embedder`` and ``reranker`` replace the Claude adapters and the
        local embedding model, e.g. with offline fakes in tests."""
        self._settings = settings
        self._generator = generator
        self._embedder = embedder
        self._reranker = reranker
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
        return IndexingService(
            loaders=default_loaders(),
            chunker=self._chunker(),
            retriever=self._repository.load(),
            repository=self._repository,
        )

    def _chunker(self) -> Chunker:
        window = SlidingWindowChunker(self._settings.chunk_size, self._settings.chunk_overlap)
        return ChunkerByType({"markdown": MarkdownChunker(window)}, default=window)

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
        return DashboardService(stats, retriever, renderer, relations)

    def question_answering_service(self) -> QuestionAnsweringService:
        return QuestionAnsweringService(
            self._ranking_retriever(), self._answer_generator(), self._highlighter
        )

    def answer_report_service(self, report_format: str = "html") -> AnswerReportService:
        """``report_format`` is a key of ``REPORT_FORMATS``."""
        try:
            renderer = REPORT_FORMATS[report_format]()
        except KeyError:
            raise ValueError(f"Unknown report format: {report_format}") from None
        return AnswerReportService(self.question_answering_service(), renderer)

    def _answer_generator(self) -> AnswerGenerator:
        if self._generator is not None:
            return self._generator
        # Imported lazily so commands that never call the API don't need credentials.
        from docsage.infrastructure.claude_generator import ClaudeAnswerGenerator

        if self._settings.model:
            return ClaudeAnswerGenerator(model=self._settings.model)
        return ClaudeAnswerGenerator()

    def catalog_service(self) -> CatalogService:
        return CatalogService(self._repository.load())

    def search_service(self) -> SearchService:
        return SearchService(self._ranking_retriever(), self._highlighter)
