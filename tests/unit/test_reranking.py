from docsage.domain.models import Chunk, SearchResult
from docsage.infrastructure.bm25 import BM25Retriever
from docsage.infrastructure.reranking import RerankingRetriever


class ReverseReranker:
    """Puts the candidates in reverse order and remembers what it was shown."""

    def __init__(self) -> None:
        self.seen: list[list[str]] = []

    def rerank(self, query, candidates):
        self.seen.append([result.chunk.id for result in candidates])
        return [
            SearchResult(result.chunk, float(rank))
            for rank, result in enumerate(reversed(candidates))
        ]


def _retriever(candidates: int = 20) -> tuple[RerankingRetriever, ReverseReranker]:
    reranker = ReverseReranker()
    retriever = RerankingRetriever(BM25Retriever(), reranker, candidates=candidates)
    retriever.add(
        Chunk(id=f"c{n}", source=f"{n}.txt", text="lisbon " * (n + 1), position=0)
        for n in range(5)
    )
    return retriever, reranker


def test_reranker_orders_the_candidates_and_the_list_is_cut_to_top_k():
    retriever, reranker = _retriever()

    results = retriever.search("lisbon", top_k=2)

    (shown,) = reranker.seen
    assert len(shown) == 5
    assert [result.chunk.id for result in results] == list(reversed(shown))[:2]


def test_reranker_sees_at_most_the_configured_candidates():
    retriever, reranker = _retriever(candidates=3)

    retriever.search("lisbon", top_k=1)

    assert len(reranker.seen[0]) == 3


def test_top_k_above_candidates_still_reaches_the_reranker():
    retriever, reranker = _retriever(candidates=2)

    assert len(retriever.search("lisbon", top_k=4)) == 4


def test_no_candidates_skips_the_reranker():
    retriever, reranker = _retriever()

    assert retriever.search("porto", top_k=3) == []
    assert reranker.seen == []


def test_storage_calls_reach_the_inner_retriever():
    retriever, _ = _retriever()

    assert len(retriever) == 5
    assert retriever.remove("0.txt") == 1
    assert {chunk.id for chunk in retriever.chunks()} == {"c1", "c2", "c3", "c4"}
