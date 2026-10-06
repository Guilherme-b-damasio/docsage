from docsage.application.services import StatsService
from docsage.domain.models import Chunk
from docsage.infrastructure.bm25 import BM25Retriever


class SizedRepository:
    def __init__(self, size):
        self._size = size

    def save(self, retriever):
        pass

    def load(self):
        return BM25Retriever()

    def size_bytes(self):
        return self._size


def _split(text):
    return text.lower().split()


def test_stats_counts_documents_chunks_and_terms():
    retriever = BM25Retriever(tokenizer=_split)
    retriever.add(
        [
            Chunk("a#0", "a.md", "alpha beta alpha", 0),
            Chunk("a#1", "a.md", "gamma", 1),
            Chunk("b#0", "b.md", "beta alpha", 0),
        ]
    )

    stats = StatsService(retriever, _split, SizedRepository(1234)).stats(top=2)

    assert stats.documents == 2
    assert stats.chunks == 3
    assert stats.terms == 6
    assert stats.vocabulary == 3
    assert stats.top_terms == (("alpha", 3), ("beta", 2))
    assert stats.index_bytes == 1234


def test_stats_of_empty_index():
    stats = StatsService(BM25Retriever(), _split, SizedRepository(0)).stats()

    assert (stats.documents, stats.chunks, stats.terms, stats.top_terms) == (0, 0, 0, ())


def test_top_term_ties_are_alphabetical():
    retriever = BM25Retriever(tokenizer=_split)
    retriever.add([Chunk("a#0", "a.md", "zeta alpha mu", 0)])

    stats = StatsService(retriever, _split, SizedRepository(0)).stats(top=3)

    assert [term for term, _ in stats.top_terms] == ["alpha", "mu", "zeta"]
