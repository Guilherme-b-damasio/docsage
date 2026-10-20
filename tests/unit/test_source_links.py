from pathlib import Path

from docsage.domain.models import Chunk
from docsage.infrastructure.source_links import FileAndUrlLocator


def _chunk(source, first_page=None):
    return Chunk(id=f"{source}#0", source=source, text="text", position=0, first_page=first_page)


def test_web_pages_link_to_their_url():
    url = "https://example.com/guide?x=1"

    assert FileAndUrlLocator().href(_chunk(url)) == url


def test_absolute_files_link_to_a_file_uri(tmp_path):
    source = tmp_path / "notes.md"

    assert FileAndUrlLocator().href(_chunk(str(source))) == source.resolve().as_uri()


def test_relative_files_resolve_from_the_base(tmp_path):
    href = FileAndUrlLocator(tmp_path).href(_chunk("docs/notes.md"))

    assert href == (tmp_path / "docs" / "notes.md").resolve().as_uri()


def test_relative_files_resolve_from_the_working_directory_by_default():
    href = FileAndUrlLocator().href(_chunk("notes.md"))

    assert href == (Path.cwd() / "notes.md").resolve().as_uri()


def test_pdf_passages_open_at_their_first_page(tmp_path):
    href = FileAndUrlLocator(tmp_path).href(_chunk("guide.pdf", first_page=3))

    assert href == (tmp_path / "guide.pdf").resolve().as_uri() + "#page=3"
