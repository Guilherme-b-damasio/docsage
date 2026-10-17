from docsage.infrastructure.chunking import MarkdownChunker
from docsage.infrastructure.html_loader import HtmlLoader, html_to_text, main_content_to_text

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


WEB_PAGE = """<html><head><title>Release notes</title></head><body>
<header><a href="/">Home</a> <a href="/blog">Blog</a></header>
<nav><ul><li>Docs</li><li>Pricing</li></ul></nav>
<main>
  <h1>Version 2</h1>
  <p>Adds a <b>watch</b> mode.</p>
  <form><label>Subscribe</label></form>
</main>
<aside>Related posts</aside>
<footer>Copyright</footer>
</body></html>"""


def test_main_content_keeps_only_the_main_element():
    text, title = main_content_to_text(WEB_PAGE)

    assert text == "# Version 2\n\nAdds a watch mode."
    assert title == "Release notes"


def test_main_content_uses_articles_when_there_is_no_main_element():
    page = (
        "<body><div>Menu</div><article><h2>First</h2><p>One</p></article>"
        "<p>Ad</p><article><p>Two</p></article></body>"
    )

    assert main_content_to_text(page)[0] == "## First\n\nOne\n\nTwo"


def test_main_content_without_main_or_article_drops_only_the_boilerplate():
    page = "<body><nav>Menu</nav><h1>Hello</h1><p>World</p><footer>Bye</footer></body>"

    assert main_content_to_text(page)[0] == "# Hello\n\nWorld"


def test_main_content_falls_back_to_the_page_when_main_holds_only_boilerplate():
    page = "<body><main><nav>Menu</nav></main><p>Real text</p></body>"

    assert main_content_to_text(page)[0] == "Real text"


def test_plain_html_to_text_still_keeps_navigation():
    assert "Pricing" in html_to_text(WEB_PAGE)[0]
