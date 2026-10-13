"""Dense-vector retrieval: a cosine-similarity retriever over an injected ``Embedder``."""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Sequence

from docsage.domain.models import Chunk, SearchResult
from docsage.domain.ports import Embedder

logger = logging.getLogger(__name__)


class EmbeddingRetriever:
    """Ranks chunks by the cosine similarity of their embedding to the query's.

    Chunks are embedded lazily, on the first search after they were added, so commands
    that only read the chunk list (stats, catalog...) never run the embedding model.
    """

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder
        self._chunks: dict[str, Chunk] = {}
        self._vectors: dict[str, list[float]] = {}

    def add(self, chunks: Iterable[Chunk]) -> None:
        for chunk in chunks:
            self._chunks[chunk.id] = chunk
            self._vectors.pop(chunk.id, None)

    def search(self, query: str, top_k: int) -> list[SearchResult]:
        if not query.strip() or not self._chunks:
            return []
        self._embed_pending()
        (query_vector,) = self._embedder.embed([query])
        scored = [
            SearchResult(chunk, _cosine(query_vector, self._vectors[chunk_id]))
            for chunk_id, chunk in self._chunks.items()
        ]
        scored.sort(key=lambda result: result.score, reverse=True)
        return [result for result in scored if result.score > 0][:top_k]

    def remove(self, source: str) -> int:
        doomed = [chunk_id for chunk_id, chunk in self._chunks.items() if chunk.source == source]
        for chunk_id in doomed:
            del self._chunks[chunk_id]
            self._vectors.pop(chunk_id, None)
        return len(doomed)

    def chunks(self) -> list[Chunk]:
        return list(self._chunks.values())

    def __len__(self) -> int:
        return len(self._chunks)

    def _embed_pending(self) -> None:
        pending = [chunk for chunk in self._chunks.values() if chunk.id not in self._vectors]
        if not pending:
            return
        vectors = self._embedder.embed([chunk.text for chunk in pending])
        self._vectors.update(zip((chunk.id for chunk in pending), vectors, strict=True))
        logger.debug("embedded chunks", extra={"chunks": len(pending)})


def _cosine(first: Sequence[float], second: Sequence[float]) -> float:
    norms = math.sqrt(sum(x * x for x in first)) * math.sqrt(sum(y * y for y in second))
    if not norms:
        return 0.0
    return sum(x * y for x, y in zip(first, second, strict=True)) / norms
