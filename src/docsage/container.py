"""Composition root: the only place that knows which adapters implement which ports."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from docsage.application.services import (
    CatalogService,
    IndexingService,
    QuestionAnsweringService,
    RemovalService,
    SearchService,
    StatsService,
)
from docsage.domain.ports import AnswerGenerator, Chunker
from docsage.infrastructure.bm25 import BM25Retriever, JsonIndexRepository
from docsage.infrastructure.chunking import ChunkerByType, MarkdownChunker, SlidingWindowChunker
from docsage.infrastructure.config import read_config
from docsage.infrastructure.highlighting import TermHighlighter
from docsage.infrastructure.loaders import default_loaders
from docsage.infrastructure.tokenizer import multilingual_tokenizer

DEFAULT_INDEX_PATH = Path(".docsage") / "index.json"


@dataclass(frozen=True)
class Settings:
    index_path: Path = DEFAULT_INDEX_PATH
    chunk_size: int = 200
    chunk_overlap: int = 40
    model: str | None = None


def load_settings(config_path: Path | None = None, **overrides: Any) -> Settings:
    """Builds settings from defaults, then the config file, then non-None overrides."""
    values = read_config(config_path) if config_path else {}
    values.update({key: value for key, value in overrides.items() if value is not None})
    return replace(Settings(), **values)


class Container:
    def __init__(self, settings: Settings, generator: AnswerGenerator | None = None) -> None:
        """``generator`` replaces the Claude adapter, e.g. with an offline fake in tests."""
        self._settings = settings
        self._generator = generator
        self._tokenizer = multilingual_tokenizer()
        self._highlighter = TermHighlighter(self._tokenizer)
        self._repository = JsonIndexRepository(
            settings.index_path, lambda: BM25Retriever(tokenizer=self._tokenizer)
        )

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

    def question_answering_service(self) -> QuestionAnsweringService:
        return QuestionAnsweringService(
            self._repository.load(), self._answer_generator(), self._highlighter
        )

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
        return SearchService(self._repository.load(), self._highlighter)
