from docsage.domain.models import Chunk, Highlight, SearchResult, TermScore
from docsage.infrastructure.html_search import HtmlSearchRenderer, PageLinks

LINKS = PageLinks(search="/ui", ask="/ui/ask", dashboard="/ui/dashboard")


def _result(source="a.md", score=1.5):
    chunk = Chunk(f"{source}#0", source, "BM25 ranks <chunks>.", 0)
    return SearchResult(
        chunk,
        score,
        (Highlight(0, 4, "bm25"),),
        (TermScore("bm25", 1.0), TermScore("ranks", 0.5)),
    )


def test_results_page_shows_ranked_highlighted_passages_with_breakdowns():
    html = HtmlSearchRenderer().render("bm25", [_result(), _result("b.md", 0.5)])

    assert "<h1>bm25</h1>" in html
    assert "2 matching passages" in html
    assert 'id="source-1"' in html and 'id="source-2"' in html
    assert '<mark title="bm25">BM25</mark>' in html
    assert "&lt;chunks&gt;" in html
    assert "Score breakdown" in html
    assert "<form" not in html


def test_results_page_says_when_nothing_matches():
    html = HtmlSearchRenderer().render("zeta", [])

    assert "No passage matches this query." in html
    assert 'class="card source"' not in html


def test_results_page_is_self_contained_and_dark_mode_aware():
    html = HtmlSearchRenderer(LINKS).render("bm25", [_result()])

    assert "prefers-color-scheme: dark" in html
    assert "http://" not in html and "https://" not in html
    assert "<script" not in html


def test_links_add_a_form_that_searches_or_asks_and_a_dashboard_link():
    html = HtmlSearchRenderer(LINKS).render('a "quoted" <query>', [])

    assert '<form class="search" method="get" action="/ui"' in html
    assert 'value="a &quot;quoted&quot; &lt;query&gt;"' in html
    assert 'formaction="/ui/ask"' in html
    assert '<a href="/ui/dashboard">Dashboard</a>' in html


def test_home_page_without_a_query_shows_only_the_form():
    html = HtmlSearchRenderer(LINKS).render("", [])

    assert "<title>docsage</title>" in html
    assert 'value=""' in html
    assert "<h1>" not in html
