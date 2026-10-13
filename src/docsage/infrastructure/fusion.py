"""Hybrid retrieval: several retrievers over the same chunks, fused by reciprocal rank."""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from docsage.domain.models import Chunk, SearchResult
from docsage.domain.ports import Retriever

RRF_K = 60
"""Damping constant from the original RRF paper (Cormack et al., 2009)."""


class ReciprocalRankFusionRetriever:
    """Asks every inner retriever for its best candidates and fuses their rankings.

    A chunk's score is ``sum(1 / (k + rank))`` over the rankings it appears in, so
    chunks that rank well in several retrievers win, and raw scores on different
    scales (BM25 vs cosine) never need to be compared.
    """

    def __init__(
        self, retrievers: Sequence[Retriever], k: int = RRF_K, candidates: int = 50
    ) -> None:
        """``candidates`` is how many results each retriever contributes (at least top_k)."""
        if not retrievers:
            raise ValueError("Reciprocal rank fusion needs at least one retriever")
        self._retrievers = tuple(retrievers)
        self._k = k
        self._candidates = candidates

    def add(self, chunks: Iterable[Chunk]) -> None:
        batch = list(chunks)
        for retriever in self._retrievers:
            retriever.add(batch)

    def search(self, query: str, top_k: int) -> list[SearchResult]:
        depth = max(top_k, self._candidates)
        scores: dict[str, float] = {}
        chunks: dict[str, Chunk] = {}
        for retriever in self._retrievers:
            for rank, result in enumerate(retriever.search(query, depth), start=1):
                chunk_id = result.chunk.id
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (self._k + rank)
                chunks.setdefault(chunk_id, result.chunk)
        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
        return [SearchResult(chunks[chunk_id], score) for chunk_id, score in ranked[:top_k]]

    def remove(self, source: str) -> int:
        counts = [retriever.remove(source) for retriever in self._retrievers]
        return counts[0]

    def chunks(self) -> list[Chunk]:
        return self._retrievers[0].chunks()

    def __len__(self) -> int:
        return len(self._retrievers[0])
