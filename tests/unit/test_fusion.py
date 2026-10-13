import pytest

from docsage.domain.models import Chunk, SearchResult
from docsage.infrastructure.bm25 import BM25Retriever
from docsage.infrastructure.fusion import RRF_K, ReciprocalRankFusionRetriever


class RankedRetriever(BM25Retriever):
    """Stores chunks like BM25 but always returns them in a fixed order of ids."""

    def __init__(self, order: list[str]) -> None:
        super().__init__()
        self._order = order
        self.depths: list[int] = []

    def search(self, query, top_k):
        self.depths.append(top_k)
        by_id = {chunk.id: chunk for chunk in self.chunks()}
        hits = [SearchResult(by_id[i], 10.0 - n) for n, i in enumerate(self._order) if i in by_id]
        return hits[:top_k]


def _chunks() -> list[Chunk]:
    return [Chunk(id=i, source=f"{i}.txt", text=f"text {i}", position=0) for i in "abcd"]


def _fused(*orders: list[str], **options) -> ReciprocalRankFusionRetriever:
    retriever = ReciprocalRankFusionRetriever([RankedRetriever(o) for o in orders], **options)
    retriever.add(_chunks())
    return retriever


def test_chunks_ranked_well_by_both_retrievers_win():
    results = _fused(["a", "b", "c"], ["b", "c", "a"]).search("q", top_k=3)

    assert [result.chunk.id for result in results] == ["b", "a", "c"]
    assert results[0].score == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 1))


def test_a_chunk_found_by_one_retriever_still_counts():
    results = _fused(["a"], ["d"]).search("q", top_k=5)

    assert {result.chunk.id for result in results} == {"a", "d"}
    assert all(result.score == pytest.approx(1 / (RRF_K + 1)) for result in results)


def test_asks_each_retriever_for_enough_candidates():
    inner = [RankedRetriever(["a"]), RankedRetriever(["b"])]
    retriever = ReciprocalRankFusionRetriever(inner, candidates=20)

    retriever.search("q", top_k=5)
    retriever.search("q", top_k=30)

    assert [r.depths for r in inner] == [[20, 30], [20, 30]]


def test_add_remove_and_chunks_reach_every_retriever():
    inner = [RankedRetriever(["a"]), RankedRetriever(["a"])]
    retriever = ReciprocalRankFusionRetriever(inner)
    retriever.add(iter(_chunks()))

    assert len(retriever) == 4 and all(len(r) == 4 for r in inner)
    assert retriever.remove("a.txt") == 1
    assert all(len(r) == 3 for r in inner)
    assert [chunk.id for chunk in retriever.chunks()] == ["b", "c", "d"]


def test_fuses_real_bm25_rankings():
    retriever = ReciprocalRankFusionRetriever([BM25Retriever(), BM25Retriever()])
    retriever.add(_chunks())

    assert retriever.search("c", top_k=1)[0].chunk.id == "c"
    assert retriever.search("nothing", top_k=3) == []


def test_needs_at_least_one_retriever():
    with pytest.raises(ValueError):
        ReciprocalRankFusionRetriever([])
