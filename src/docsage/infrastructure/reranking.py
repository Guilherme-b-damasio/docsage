"""Two-stage retrieval: a fast retriever proposes candidates, a reranker orders them."""

from __future__ import annotations

from collections.abc import Iterable

from docsage.domain.models import Chunk, SearchResult
from docsage.domain.ports import Reranker, Retriever


class RerankingRetriever:
    """Wraps a retriever and lets a ``Reranker`` reorder its best ``candidates`` results.

    Storage calls go straight to the inner retriever, so the decorator can be put in
    front of any retriever without changing what is indexed.
    """

    def __init__(self, inner: Retriever, reranker: Reranker, candidates: int = 20) -> None:
        """``candidates`` is how many results the reranker sees (at least top_k)."""
        self._inner = inner
        self._reranker = reranker
        self._candidates = candidates

    def add(self, chunks: Iterable[Chunk]) -> None:
        self._inner.add(chunks)

    def search(self, query: str, top_k: int) -> list[SearchResult]:
        candidates = self._inner.search(query, max(top_k, self._candidates))
        if not candidates:
            return []
        return self._reranker.rerank(query, candidates)[:top_k]

    def remove(self, source: str) -> int:
        return self._inner.remove(source)

    def chunks(self) -> list[Chunk]:
        return self._inner.chunks()

    def __len__(self) -> int:
        return len(self._inner)
