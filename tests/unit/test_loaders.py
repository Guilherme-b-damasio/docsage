from pypdf import PdfWriter

from docsage.infrastructure.loaders import PAGE_SEPARATOR, PdfLoader, default_loaders


def test_pdf_loader_records_page_count_and_offsets(tmp_path):
    path = tmp_path / "blank.pdf"
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=200, height=200)
    with path.open("wb") as handle:
        writer.write(handle)

    document = PdfLoader().load(path)

    assert document.source == str(path)
    assert document.metadata == {"type": "pdf", "pages": "3"}
    assert document.text == PAGE_SEPARATOR * 2
    assert document.page_offsets == (0, 2, 4)


def test_default_loaders_route_by_extension(tmp_path):
    supported = [
        name
        for name in ("a.md", "b.PDF", "c.rst", "d.png")
        if any(loader.supports(tmp_path / name) for loader in default_loaders())
    ]
    assert supported == ["a.md", "b.PDF", "c.rst"]
