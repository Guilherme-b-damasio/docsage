import pytest

from docsage.application.services import DashboardService, StatsService, file_type, histogram
from docsage.domain.models import Chunk, HistogramBin
from docsage.infrastructure.bm25 import BM25Retriever


class SizedRepository:
    def save(self, retriever):
        pass

    def load(self):
        return BM25Retriever()

    def size_bytes(self):
        return 2048


class RecordingRenderer:
    def __init__(self):
        self.overviews = []

    def render(self, overview):
        self.overviews.append(overview)
        return "rendered"


def _split(text):
    return text.lower().split()


def _service(chunks, renderer=None):
    retriever = BM25Retriever(tokenizer=_split)
    retriever.add(chunks)
    stats = StatsService(retriever, _split, SizedRepository())
    return DashboardService(stats, retriever, renderer or RecordingRenderer())


def test_file_type_uses_the_lowercase_extension():
    assert file_type("docs/Guide.PDF") == "pdf"
    assert file_type("notes.md") == "md"
    assert file_type("Makefile") == "other"


def test_histogram_keeps_empty_ranges_and_covers_every_value():
    bins = histogram([1, 2, 3, 10], 3)

    assert bins == (HistogramBin(1, 4, 3), HistogramBin(5, 8, 0), HistogramBin(9, 10, 1))
    assert sum(item.count for item in bins) == 4


def test_histogram_of_identical_values_is_one_bin():
    assert histogram([5, 5], 10) == (HistogramBin(5, 5, 2),)


def test_histogram_edge_cases():
    assert histogram([], 10) == ()
    with pytest.raises(ValueError):
        histogram([1], 0)


def test_overview_counts_types_lengths_and_terms():
    service = _service(
        [
            Chunk("a#0", "a.md", "alpha beta alpha", 0),
            Chunk("a#1", "a.md", "gamma", 1),
            Chunk("b#0", "b.md", "beta", 0),
            Chunk("c#0", "c.pdf", "alpha beta gamma delta", 0),
        ]
    )

    overview = service.overview(top=2, bins=4)

    assert (overview.documents, overview.chunks, overview.index_bytes) == (3, 4, 2048)
    assert overview.documents_by_type == (("md", 2), ("pdf", 1))
    assert [item.count for item in overview.chunk_lengths] == [2, 0, 1, 1]
    assert overview.top_terms == (("alpha", 3), ("beta", 3))


def test_render_passes_the_overview_to_the_renderer():
    renderer = RecordingRenderer()
    service = _service([Chunk("a#0", "a.md", "alpha", 0)], renderer)

    assert service.render() == "rendered"
    assert renderer.overviews[0].documents == 1


def test_overview_of_an_empty_index():
    overview = _service([]).overview()

    assert overview.documents == 0
    assert overview.documents_by_type == ()
    assert overview.chunk_lengths == ()
