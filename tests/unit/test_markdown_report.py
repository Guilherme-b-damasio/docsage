from docsage.domain.models import Answer, Chunk, Highlight, SearchResult, TermScore, TokenUsage
from docsage.infrastructure.markdown_report import MarkdownAnswerRenderer


class _Locator:
    def __init__(self, href=None):
        self._href = href

    def href(self, chunk):
        return self._href


def _result(text="BM25 ranks chunks.\nSecond line.", source="a.md", **kwargs):
    return SearchResult(Chunk(f"{source}#0", source, text, 0), 2.5, **kwargs)


def test_markdown_report_starts_with_the_question_and_the_answer():
    markdown = MarkdownAnswerRenderer(_Locator()).render(Answer("What is\nBM25?", "A rank.", ()))

    assert markdown.splitlines()[:3] == ["# What is BM25?", "", "A rank."]
    assert "## Sources" not in markdown


def test_markdown_report_links_citations_to_existing_passages_only():
    answer = Answer("Q?", "See [1] and [2].", (_result(),))

    markdown = MarkdownAnswerRenderer(_Locator()).render(answer)

    assert "See [\\[1\\]](#source-1) and [2]." in markdown
    assert '<a id="source-1"></a>' in markdown


def test_markdown_report_quotes_each_passage_with_highlights():
    result = _result(highlights=(Highlight(0, 4, "bm25"),))

    markdown = MarkdownAnswerRenderer(_Locator()).render(Answer("Q?", "A.", (result,)))

    assert "### [1] a.md\n\nScore 2.50\n\n> **BM25** ranks chunks.\n> Second line." in markdown


def test_markdown_report_links_each_citation_to_its_source():
    result = _result(source="docs/[draft].md")
    renderer = MarkdownAnswerRenderer(_Locator("file:///docs/%5Bdraft%5D.md"))

    markdown = renderer.render(Answer("Q?", "A.", (result,)))

    assert "### [1] [docs/\\[draft\\].md](<file:///docs/%5Bdraft%5D.md>)" in markdown


def test_markdown_report_spells_out_the_score_breakdown():
    result = _result(contributions=(TermScore("bm25", 1.2), TermScore("ranks", 0.3)))

    markdown = MarkdownAnswerRenderer(_Locator()).render(Answer("Q?", "A.", (result,)))

    assert "Score breakdown: `bm25 1.20 + ranks 0.30`" in markdown


def test_markdown_report_ends_with_the_usage_line():
    usage = TokenUsage(model="m", input_tokens=10, output_tokens=2)

    markdown = MarkdownAnswerRenderer(_Locator()).render(
        Answer("q?", "a", (), usage=usage, cost_usd=0.5)
    )

    assert markdown.endswith("---\n\n*Usage: m: 10 input tokens, 2 output tokens, ~$0.5000*\n")


def test_markdown_report_links_files_by_default(tmp_path):
    source = tmp_path / "a.md"

    markdown = MarkdownAnswerRenderer().render(Answer("Q?", "A.", (_result(source=str(source)),)))

    assert f"(<{source.resolve().as_uri()}#:~:text=" in markdown


def test_markdown_report_says_which_part_of_the_index_it_answered_from():
    answer = Answer("q", "Alpha is in [1].", (_result(),), source="docs")

    assert "## Sources in `docs`" in MarkdownAnswerRenderer().render(answer)


def test_markdown_report_of_the_whole_index_names_no_source_filter():
    answer = Answer("q", "Alpha is in [1].", (_result(),))

    assert "## Sources\n" in MarkdownAnswerRenderer().render(answer)


def _indexed(source, chunk_id, indexed_at, text="The index keeps chunks."):
    return SearchResult(Chunk(chunk_id, source, text, 0, indexed_at=indexed_at), 1.0)


def test_markdown_report_groups_the_passages_by_document_newest_first():
    answer = Answer(
        "Q?",
        "A [1][2][3].",
        (
            _indexed("old.md", "old#0", "2026-10-01T09:00:00+00:00"),
            _indexed("new.md", "new#0", "2026-10-20T09:30:00+00:00"),
            _indexed("old.md", "old#1", "2026-10-01T09:00:00+00:00"),
        ),
    )

    markdown = MarkdownAnswerRenderer(_Locator()).render(answer)

    assert markdown.index("### new.md") < markdown.index("### old.md")
    assert markdown.count("### old.md") == 1
    assert markdown.index("#### [2]") < markdown.index("#### [1]") < markdown.index("#### [3]")


def test_markdown_report_says_how_many_passages_a_document_contributed_and_when_indexed():
    answer = Answer(
        "Q?",
        "A [1][2].",
        (
            _indexed("notes.md", "n#0", "2026-10-20T09:30:00+00:00"),
            _indexed("notes.md", "n#1", "2026-10-20T09:30:00+00:00"),
        ),
    )

    markdown = MarkdownAnswerRenderer(_Locator()).render(answer)

    assert "### notes.md\n\n2 passages cited, indexed 2026-10-20 09:30 UTC" in markdown


def test_markdown_report_calls_an_unrecorded_index_time_unknown():
    answer = Answer("Q?", "A [1].", (_indexed("notes.md", "n#0", ""),))

    markdown = MarkdownAnswerRenderer(_Locator()).render(answer)

    assert "1 passage cited, indexed unknown" in markdown


def test_markdown_report_escapes_a_documents_name():
    answer = Answer("Q?", "A [1].", (_indexed("[odd].md", "o#0", ""),))

    markdown = MarkdownAnswerRenderer(_Locator()).render(answer)

    assert r"### \[odd\].md" in markdown
