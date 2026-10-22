from docsage.domain.models import DocumentRelation, HistogramBin, IndexOverview, RecentDocument
from docsage.infrastructure.text_dashboard import TextDashboardRenderer, bars


def test_bars_scale_to_the_largest_value():
    assert bars([("md", 4), ("pdf", 2), ("x", 0)], width=4) == [
        "  md   ████ 4",
        "  pdf  ██ 2",
        "  x     0",
    ]


def test_text_dashboard_lists_totals_and_charts():
    overview = IndexOverview(
        documents=2,
        chunks=3,
        terms=1500,
        vocabulary=9,
        index_bytes=512,
        documents_by_type=(("md", 2),),
        chunk_lengths=(HistogramBin(1, 4, 2), HistogramBin(5, 5, 1)),
        top_terms=(("alpha", 3),),
    )

    text = TextDashboardRenderer().render(overview)

    assert "Terms:      1,500 (9 distinct)" in text
    assert "Index size: 512 B" in text
    assert "Chunk length (words):\n  1-4" in text
    assert "  5  " in text
    assert "Top terms:\n  alpha" in text


def test_text_dashboard_of_an_empty_index_has_no_charts():
    overview = IndexOverview(0, 0, 0, 0, 0, (), (), ())
    assert ":\n  " not in TextDashboardRenderer().render(overview)


def test_text_dashboard_lists_related_documents():
    relation = DocumentRelation("docs/a.md", "b.md", ("bm25", "ranking"))
    overview = IndexOverview(2, 2, 6, 4, 10, (("md", 2),), (), (), (relation,))

    text = TextDashboardRenderer().render(overview)

    assert "Related documents (shared top terms):\n  a.md <-> b.md: bm25, ranking" in text


def test_text_dashboard_lists_recently_indexed_documents():
    recent = (
        RecentDocument("new.md", "2026-10-22T09:30:00+00:00", 3),
        RecentDocument("old.md", "", 1),
    )
    overview = IndexOverview(2, 4, 6, 4, 10, (("md", 2),), (), (), recent_documents=recent)

    text = TextDashboardRenderer().render(overview)

    assert (
        "Recently indexed:\n"
        "  2026-10-22 09:30 UTC  new.md (3 chunks)\n"
        "  unknown               old.md (1 chunk)"
    ) in text
