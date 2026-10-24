import pytest

from docsage.infrastructure.loaders import default_loaders
from docsage.infrastructure.source_text import LoaderSourceTextReader


@pytest.fixture
def reader():
    return LoaderSourceTextReader(default_loaders())


def test_reader_returns_a_text_sources_contents(tmp_path, reader):
    source = tmp_path / "notes.md"
    source.write_text("# Notes\n\nThe index keeps chunks.\n", encoding="utf-8")

    assert reader.text(str(source)) == "# Notes\n\nThe index keeps chunks.\n"


def test_reader_does_not_fetch_a_web_page_again(reader):
    assert reader.text("https://example.com/guide") is None


def test_reader_returns_none_for_a_format_no_loader_reads(tmp_path, reader):
    source = tmp_path / "archive.zip"
    source.write_bytes(b"PK\x03\x04")

    assert reader.text(str(source)) is None


def test_reader_returns_none_when_the_file_is_gone(tmp_path, reader):
    assert reader.text(str(tmp_path / "missing.md")) is None


class _BrokenLoader:
    def supports(self, path):
        return True

    def load(self, path):
        raise ValueError("not readable")


def test_reader_returns_none_when_the_loader_cannot_read_the_document(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text("text", encoding="utf-8")

    assert LoaderSourceTextReader([_BrokenLoader()]).text(str(source)) is None
