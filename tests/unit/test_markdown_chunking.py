from docsage.domain.models import Document
from docsage.infrastructure.chunking import (
    ChunkerByType,
    MarkdownChunker,
    SlidingWindowChunker,
    markdown_sections,
)
from docsage.infrastructure.loaders import PlainTextLoader

GUIDE = """Intro line before any heading.

# Guide

Welcome text.

## Setup

### Install

Run pip install.

## Usage ##

```bash
# not a heading
docsage index .
```

# Appendix
Extra notes.
"""


def test_sections_carry_the_heading_path():
    sections = markdown_sections(GUIDE)

    assert [path for path, _ in sections] == [
        "",
        "Guide",
        "Guide > Setup > Install",
        "Guide > Usage",
        "Appendix",
    ]


def test_section_text_starts_with_its_heading():
    sections = dict(markdown_sections(GUIDE))

    assert sections["Guide > Setup > Install"].splitlines()[0] == "### Install"
    assert "Run pip install." in sections["Guide > Setup > Install"]


def test_headings_inside_code_fences_are_ignored():
    usage = dict(markdown_sections(GUIDE))["Guide > Usage"]

    assert "# not a heading" in usage
    assert "docsage index ." in usage


def test_heading_only_sections_are_dropped():
    assert "Guide > Setup" not in dict(markdown_sections(GUIDE))


def test_document_without_headings_is_one_section():
    assert markdown_sections("just text\nmore") == [("", "just text\nmore")]


def test_chunks_never_cross_sections_and_keep_positions_unique():
    chunker = MarkdownChunker(SlidingWindowChunker(size=3, overlap=0))

    chunks = chunker.split(Document(source="guide.md", text=GUIDE))

    assert [c.position for c in chunks] == list(range(len(chunks)))
    assert len({c.id for c in chunks}) == len(chunks)
    install = [c for c in chunks if c.section == "Guide > Setup > Install"]
    assert " ".join(c.text for c in install) == "### Install Run pip install."
    assert install[0].citation == "guide.md, Guide > Setup > Install"


def test_long_sections_are_split_by_the_body_chunker():
    text = "# Title\n\n" + " ".join(f"w{i}" for i in range(10))

    chunks = MarkdownChunker(SlidingWindowChunker(size=4, overlap=1)).split(
        Document(source="a.md", text=text)
    )

    assert len(chunks) > 1
    assert {c.section for c in chunks} == {"Title"}


class _Recorder:
    def __init__(self, name):
        self.name = name

    def split(self, document):
        return [self.name]


def test_chunker_by_type_routes_on_document_type():
    chunker = ChunkerByType({"markdown": _Recorder("md")}, default=_Recorder("window"))

    assert chunker.split(Document("a.md", "x", {"type": "markdown"})) == ["md"]
    assert chunker.split(Document("a.pdf", "x", {"type": "pdf"})) == ["window"]
    assert chunker.split(Document("a", "x")) == ["window"]


def test_plain_text_loader_marks_markdown_files(tmp_path):
    (tmp_path / "a.md").write_text("# T", encoding="utf-8")
    (tmp_path / "b.txt").write_text("t", encoding="utf-8")
    loader = PlainTextLoader()

    assert loader.load(tmp_path / "a.md").metadata["type"] == "markdown"
    assert loader.load(tmp_path / "b.txt").metadata["type"] == "text"
