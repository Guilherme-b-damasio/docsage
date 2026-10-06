"""Composition root: the only place that knows which adapters implement which ports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from docsage.application.services import (
    IndexingService,
    QuestionAnsweringService,
    RemovalService,
)
from docsage.domain.ports import Retriever
from docsage.infrastructure.bm25 import JsonIndexRepository
from docsage.infrastructure.chunking import SlidingWindowChunker
from docsage.infrastructure.loaders import default_loaders

DEFAULT_INDEX_PATH = Path(".docsage") / "index.json"


@dataclass(frozen=True)
class Settings:
    index_path: Path = DEFAULT_INDEX_PATH
    chunk_size: int = 200
    chunk_overlap: int = 40
    model: str | None = None


class Container:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._repository = JsonIndexRepository(settings.index_path)

    def indexing_service(self) -> IndexingService:
        return IndexingService(
            loaders=default_loaders(),
            chunker=SlidingWindowChunker(
                self._settings.chunk_size, self._settings.chunk_overlap
            ),
            retriever=self._repository.load(),
            repository=self._repository,
        )

    def removal_service(self) -> RemovalService:
        return RemovalService(self._repository.load(), self._repository)

    def question_answering_service(self) -> QuestionAnsweringService:
        # Imported lazily so commands that never call the API don't need credentials.
        from docsage.infrastructure.claude_generator import ClaudeAnswerGenerator

        generator = (
            ClaudeAnswerGenerator(model=self._settings.model)
            if self._settings.model
            else ClaudeAnswerGenerator()
        )
        return QuestionAnsweringService(self._repository.load(), generator)

    def retriever(self) -> Retriever:
        return self._repository.load()
