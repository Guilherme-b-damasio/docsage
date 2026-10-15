from docsage.infrastructure.chunking import MarkdownChunker
from docsage.infrastructure.html_loader import HtmlLoader, html_to_text

PAGE = """<!doctype html>
<html>
<head>
  <title>Guide &amp; FAQ</title>
  <style>p { color: red; }</style>
  <script>var hidden = "never indexed";</script>
</head>
<body>
  <h1>Setup</h1>
  <p>Install   docsage<br>then <b>run</b> it.</p>
  <h2>Install <small>v2</small></h2>
  <ul><li>pip install</li><li>uv add</li></ul>
  <noscript>Enable JavaScript</noscript>
</body>
</html>
"""


def test_headings_become_markdown_heading_lines():
    text, _ = html_to_text(PAGE)

    assert text.splitlines()[0] == "# Setup"
    assert "## Install v2" in text.splitlines()


def test_tags_are_stripped_and_blocks_start_new_lines():
    text, _ = html_to_text(PAGE)

    assert text == (
        "# Setup\n\nInstall docsage\n\nthen run it.\n\n## Install v2\n\npip install\n\nuv add"
    )


def test_scripts_styles_and_noscript_are_not_text():
    text, _ = html_to_text(PAGE)

    assert "never indexed" not in text
    assert "color" not in text
    assert "JavaScript" not in text


def test_title_is_returned_with_entities_decoded():
    assert html_to_text(PAGE)[1] == "Guide & FAQ"


def test_preformatted_text_keeps_its_lines_inside_a_fence():
    text, _ = html_to_text("<p>Run:</p><pre>\n# not a heading\n  indented\n</pre>")

    assert text == "Run:\n\n```\n# not a heading\n  indented\n```"


def test_paragraphs_that_look_like_headings_are_escaped():
    text, _ = html_to_text("<p># 1 rule</p><p>#hashtag</p>")

    assert text.splitlines()[0] == "\\# 1 rule"
    assert text.splitlines()[-1] == "#hashtag"


def test_table_cells_are_separated_and_rows_are_lines():
    text, _ = html_to_text(
        "<table><tr><th>Name</th><th>Size</th></tr><tr><td>a</td><td>1</td></tr></table>"
    )

    assert text == "Name Size\n\na 1"


def test_loader_reads_html_files_with_their_title(tmp_path):
    path = tmp_path / "guide.HTML"
    path.write_text(PAGE, encoding="utf-8")
    loader = HtmlLoader()

    document = loader.load(path)

    assert loader.supports(path)
    assert loader.supports(tmp_path / "page.htm")
    assert not loader.supports(tmp_path / "notes.md")
    assert document.metadata == {"type": "html", "title": "Guide & FAQ"}
    assert document.text.startswith("# Setup")


def test_loader_without_a_title_leaves_it_out(tmp_path):
    path = tmp_path / "bare.html"
    path.write_text("<p>hello</p>", encoding="utf-8")

    assert HtmlLoader().load(path).metadata == {"type": "html"}


def test_markdown_chunker_cites_html_sections(tmp_path):
    path = tmp_path / "guide.html"
    path.write_text(PAGE, encoding="utf-8")

    chunks = MarkdownChunker().split(HtmlLoader().load(path))

    assert [chunk.section for chunk in chunks] == ["Setup", "Setup > Install v2"]
    assert chunks[1].citation == f"{path}, Setup > Install v2"
