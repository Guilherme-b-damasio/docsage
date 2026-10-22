import pytest

from docsage.application.services import (
    DashboardService,
    RelationService,
    StatsService,
    file_type,
    histogram,
    recent_documents,
)
from docsage.domain.models import Chunk, DocumentRelation, HistogramBin, RecentDocument
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


def test_file_type_of_a_web_page_is_web():
    assert file_type("https://example.com/guide.html") == "web"


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


def test_render_overview_renders_an_overview_built_earlier():
    renderer = RecordingRenderer()
    service = _service([Chunk("a#0", "a.md", "alpha", 0)], renderer)
    overview = service.overview()

    assert service.render_overview(overview) == "rendered"
    assert renderer.overviews == [overview]



def _relations(texts, terms_per_document=10):
    retriever = BM25Retriever(tokenizer=_split)
    retriever.add(
        Chunk(f"{source}#0", source, text, 0) for source, text in texts.items()
    )
    return RelationService(retriever, _split, terms_per_document)


def test_relations_link_documents_that_share_top_terms():
    service = _relations(
        {
            "a.md": "retrieval ranking ranking bm25",
            "b.md": "ranking bm25 install",
            "c.md": "cooking recipes pasta",
        }
    )

    assert service.relations() == (
        DocumentRelation("a.md", "b.md", ("ranking", "bm25")),
    )


def test_relations_skip_short_terms_and_numbers():
    service = _relations({"a.md": "is 2024 alpha", "b.md": "is 2024 beta"})

    assert service.relations() == ()
    assert service.top_terms() == {"a.md": ("alpha",), "b.md": ("beta",)}


def test_top_terms_prefer_terms_that_are_not_everywhere():
    service = _relations(
        {"a.md": "common common common rare", "b.md": "common other", "c.md": "common"},
        terms_per_document=1,
    )

    assert service.top_terms()["a.md"] == ("rare",)


def test_relations_are_ordered_by_strength_and_limited():
    service = _relations(
        {
            "a.md": "alpha beta gamma",
            "b.md": "alpha beta delta",
            "c.md": "alpha epsilon zeta",
            "d.md": "unrelated words here",
        }
    )

    relations = service.relations(limit=2)

    assert [(item.first, item.second, item.strength) for item in relations] == [
        ("a.md", "b.md", 2),
        ("a.md", "c.md", 1),
    ]


def test_overview_includes_relations_when_a_relation_service_is_given():
    retriever = BM25Retriever(tokenizer=_split)
    retriever.add([Chunk("a#0", "a.md", "alpha beta", 0), Chunk("b#0", "b.md", "alpha", 0)])
    stats = StatsService(retriever, _split, SizedRepository())
    relations = RelationService(retriever, _split)

    with_relations = DashboardService(stats, retriever, RecordingRenderer(), relations)
    without = DashboardService(stats, retriever, RecordingRenderer())

    assert with_relations.overview().relations == (DocumentRelation("a.md", "b.md", ("alpha",)),)
    assert without.overview().relations == ()


class DiagonalProjector:
    def __init__(self):
        self.calls = 0

    def project(self, chunks):
        from docsage.domain.models import ChunkPoint

        self.calls += 1
        return [ChunkPoint(c.id, c.source, n / 10, -n / 10) for n, c in enumerate(chunks)]


def test_overview_maps_chunks_when_a_projector_is_given():
    retriever = BM25Retriever(tokenizer=_split)
    retriever.add([Chunk("a#0", "a.md", "alpha", 0), Chunk("b#0", "b.md", "beta", 0)])
    stats = StatsService(retriever, _split, SizedRepository())
    projector = DiagonalProjector()

    service = DashboardService(stats, retriever, RecordingRenderer(), projector=projector)

    points = service.overview().chunk_map
    assert [(p.chunk_id, p.x, p.y) for p in points] == [("a#0", 0.0, 0.0), ("b#0", 0.1, -0.1)]
    assert _service([Chunk("a#0", "a.md", "alpha", 0)]).overview().chunk_map == ()


def test_empty_index_skips_the_projector():
    projector = DiagonalProjector()
    retriever = BM25Retriever(tokenizer=_split)
    stats = StatsService(retriever, _split, SizedRepository())

    service = DashboardService(stats, retriever, RecordingRenderer(), projector=projector)

    assert service.overview().chunk_map == ()
    assert projector.calls == 0


def test_overview_lists_recently_indexed_documents_newest_first():
    chunks = [
        Chunk("old.md#0", "old.md", "alpha", 0, indexed_at="2026-10-01T08:00:00+00:00"),
        Chunk("new.md#0", "new.md", "beta", 0, indexed_at="2026-10-22T09:00:00+00:00"),
        Chunk("new.md#1", "new.md", "gamma", 1, indexed_at="2026-10-22T09:00:00+00:00"),
        Chunk("also.md#0", "also.md", "delta", 0, indexed_at="2026-10-22T09:00:00+00:00"),
        Chunk("legacy.md#0", "legacy.md", "epsilon", 0),
    ]

    overview = _service(chunks).overview()

    assert overview.recent_documents == (
        RecentDocument("also.md", "2026-10-22T09:00:00+00:00", 1),
        RecentDocument("new.md", "2026-10-22T09:00:00+00:00", 2),
        RecentDocument("old.md", "2026-10-01T08:00:00+00:00", 1),
        RecentDocument("legacy.md", "", 1),
    )


def test_recent_documents_are_capped():
    chunks = [
        Chunk(f"{name}#0", name, "text", 0, indexed_at=f"2026-10-0{day}T00:00:00+00:00")
        for day, name in enumerate(["a.md", "b.md", "c.md"], start=1)
    ]

    assert recent_documents(chunks, 2) == (
        RecentDocument("c.md", "2026-10-03T00:00:00+00:00", 1),
        RecentDocument("b.md", "2026-10-02T00:00:00+00:00", 1),
    )
    assert recent_documents(chunks, 0) == ()
    assert _service([]).overview().recent_documents == ()
