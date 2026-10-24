from docsage.domain.models import Answer, Chunk, Highlight, SearchResult
from docsage.infrastructure.highlighting import TermHighlighter
from docsage.infrastructure.html_self_contained import SelfContainedHtmlAnswerRenderer
from docsage.infrastructure.tokenizer import multilingual_tokenizer

DOCUMENT = (
    "# Notes\n\nBM25 ranks chunks by term weight.\n\nEmbeddings place chunks on a map.\n"
)


class _Reader:
    """A ``SourceTextReader`` over texts held in memory."""

    def __init__(self, texts):
        self._texts = texts
        self.asked = []

    def text(self, source):
        self.asked.append(source)
        return self._texts.get(source)


def _result(source="notes.md", chunk_id="notes#0", text="BM25 ranks chunks by term weight."):
    return SearchResult(Chunk(chunk_id, source, text, 0), 1.25)


def _renderer(texts, highlighter=None):
    return SelfContainedHtmlAnswerRenderer(_Reader(texts), highlighter)


def test_report_inlines_the_cited_document_with_the_passage_marked():
    answer = Answer("How does BM25 work?", "It weighs terms [1].", (_result(),))

    html = _renderer({"notes.md": DOCUMENT}).render(answer)

    assert "<h2>Documents</h2>" in html
    assert "1 cited document inlined below" in html
    assert '<span class="anchor" id="passage-1"></span>' in html
    assert '<pre class="passage" tabindex="-1">BM25 ranks chunks by term weight.</pre>' in html
    # The text around the passage is inlined too, so the citation keeps its context.
    assert "<pre># Notes" in html
    assert "Embeddings place chunks on a map." in html


def test_report_points_an_inlined_citation_at_the_copy_inside_the_page():
    answer = Answer("Q?", "A [1].", (_result(),))

    html = _renderer({"notes.md": DOCUMENT}).render(answer)

    assert 'href="#passage-1"' in html
    assert "file://" not in html


def test_report_keeps_an_inlined_citation_in_the_same_tab():
    answer = Answer("Q?", "A [1].", (_result(),))

    html = _renderer({"notes.md": DOCUMENT}).render(answer)

    assert 'href="#passage-1" title="Go to the document below"' in html
    assert "_blank" not in html


def test_report_links_back_from_an_inlined_document_to_the_passages_card():
    answer = Answer("Q?", "A [1].", (_result(),))

    html = _renderer({"notes.md": DOCUMENT}).render(answer)

    assert '1 passage cited, back to <a href="#source-1">[1]</a>' in html


def test_report_keeps_the_ordinary_link_for_a_source_it_cannot_read_back():
    answer = Answer("Q?", "A [1].", (_result(source="https://example.com/guide"),))

    html = _renderer({}).render(answer)

    assert "<h2>Documents</h2>" not in html
    assert 'href="https://example.com/guide#:~:text=' in html


def test_report_leaves_out_a_document_that_no_longer_holds_the_passage(tmp_path):
    answer = Answer("Q?", "A [1].", (_result(),))

    html = _renderer({"notes.md": "The document was rewritten.\n"}).render(answer)

    assert "<h2>Documents</h2>" not in html
    assert '<pre class="passage"' not in html


def test_report_inlines_every_document_it_cites():
    answer = Answer(
        "Q?",
        "A [1][2].",
        (
            _result(),
            _result("map.md", "map#0", "Embeddings place chunks on a map."),
        ),
    )

    html = _renderer({"notes.md": DOCUMENT, "map.md": DOCUMENT}).render(answer)

    assert "2 cited documents inlined below" in html
    assert html.count('<section class="inlined">') == 2
    assert 'id="passage-1"' in html and 'id="passage-2"' in html


def test_report_marks_two_passages_of_one_document_separately():
    answer = Answer(
        "Q?",
        "A [1][2].",
        (
            _result(),
            _result("notes.md", "notes#1", "Embeddings place chunks on a map."),
        ),
    )

    html = _renderer({"notes.md": DOCUMENT}).render(answer)

    assert html.count('<section class="inlined">') == 1
    assert html.count('<pre class="passage" tabindex="-1">') == 2
    assert "2 passages cited, back to" in html


def test_report_gives_overlapping_passages_one_marked_stretch_with_both_anchors():
    overlapping = _result("notes.md", "notes#1", "ranks chunks by term weight.")
    answer = Answer("Q?", "A [1][2].", (_result(), overlapping))

    html = _renderer({"notes.md": DOCUMENT}).render(answer)

    assert html.count('<pre class="passage" tabindex="-1">') == 1
    assert '<span class="anchor" id="passage-1"></span>' in html
    assert '<span class="anchor" id="passage-2"></span>' in html
    assert 'href="#passage-2"' in html


def test_report_highlights_the_matched_terms_inside_the_inlined_passage():
    result = SearchResult(
        Chunk("notes#0", "notes.md", "BM25 ranks chunks by term weight.", 0),
        1.25,
        (Highlight(0, 4, "bm25"),),
    )
    answer = Answer("Q?", "A [1].", (result,))

    renderer = _renderer({"notes.md": DOCUMENT}, TermHighlighter(multilingual_tokenizer()))

    html = renderer.render(answer)

    assert '<pre class="passage" tabindex="-1"><mark title="bm25">BM25</mark> ranks' in html


def test_report_escapes_the_inlined_document():
    answer = Answer("Q?", "A [1].", (_result(text="<script>alert(1)</script>"),))

    html = _renderer({"notes.md": "before <script>alert(1)</script> after"}).render(answer)

    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_report_reads_each_cited_document_once():
    reader = _Reader({"notes.md": DOCUMENT})
    answer = Answer(
        "Q?",
        "A [1][2].",
        (_result(), _result("notes.md", "notes#1", "Embeddings place chunks on a map.")),
    )

    SelfContainedHtmlAnswerRenderer(reader).render(answer)

    assert reader.asked == ["notes.md"]


def test_report_without_sources_is_still_a_page():
    html = _renderer({}).render(Answer("Q?", "No relevant context found.", ()))

    assert html.startswith("<!doctype html>")
    assert "<h2>Documents</h2>" not in html
    assert "<h2>Sources</h2>" not in html
