import zipfile

import pytest

from docsage.infrastructure.chunking import MarkdownChunker, SlidingWindowChunker
from docsage.infrastructure.docx_loader import DocxLoader, docx_to_text, heading_levels

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def paragraph(text, style=None, outline=None):
    properties = ""
    if style or outline is not None:
        inner = f'<w:pStyle w:val="{style}"/>' if style else ""
        inner += f'<w:outlineLvl w:val="{outline}"/>' if outline is not None else ""
        properties = f"<w:pPr>{inner}</w:pPr>"
    return f"<w:p>{properties}<w:r><w:t xml:space=\"preserve\">{text}</w:t></w:r></w:p>"


def document_xml(*blocks):
    return f"<w:document {NS}><w:body>{''.join(blocks)}<w:sectPr/></w:body></w:document>"


STYLES = f"""<w:styles {NS}>
  <w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>
  <w:style w:type="paragraph" w:styleId="Ttulo1"><w:name w:val="heading 1"/></w:style>
  <w:style w:type="paragraph" w:styleId="Ttulo2"><w:name w:val="heading 2"/></w:style>
  <w:style w:type="paragraph" w:styleId="Capitulo">
    <w:name w:val="Capitulo"/><w:pPr><w:outlineLvl w:val="0"/></w:pPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="CapituloAzul">
    <w:name w:val="Capitulo azul"/><w:basedOn w:val="Capitulo"/>
  </w:style>
  <w:style w:type="character" w:styleId="Heading1Char"><w:name w:val="heading 1"/></w:style>
</w:styles>"""

CORE = """<cp:coreProperties
  xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
  xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Install  guide</dc:title>
</cp:coreProperties>"""


def write_docx(path, body, styles=STYLES, core=CORE):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", body)
        if styles:
            archive.writestr("word/styles.xml", styles)
        if core:
            archive.writestr("docProps/core.xml", core)
    return path


def test_heading_levels_come_from_localized_names_outline_levels_and_based_on():
    assert heading_levels(STYLES.encode()) == {
        "Ttulo1": 1,
        "Ttulo2": 2,
        "Capitulo": 1,
        "CapituloAzul": 1,
    }


def test_heading_paragraphs_become_markdown_heading_lines():
    body = document_xml(
        paragraph("Setup", "Ttulo1"),
        paragraph("Install   the package."),
        paragraph("Upgrade", "Ttulo2"),
        paragraph("Run the upgrade."),
    )

    text = docx_to_text(body.encode(), STYLES.encode())

    assert text == "# Setup\n\nInstall the package.\n\n## Upgrade\n\nRun the upgrade."


def test_english_style_ids_are_headings_even_without_a_styles_part():
    body = document_xml(paragraph("Guide", "Title"), paragraph("Setup", "Heading2"))

    assert docx_to_text(body.encode()) == "# Guide\n\n## Setup"


def test_paragraph_outline_level_marks_a_heading_and_level_nine_is_body_text():
    body = document_xml(paragraph("Chapter", outline=2), paragraph("Body", outline=9))

    assert docx_to_text(body.encode()) == "### Chapter\n\nBody"


def test_runs_tabs_and_breaks_are_joined_and_empty_paragraphs_dropped():
    body = document_xml(
        '<w:p><w:r><w:t>Hello</w:t><w:tab/><w:t>wide</w:t><w:br/></w:r>'
        "<w:r><w:t>world</w:t></w:r></w:p>",
        "<w:p/>",
    )

    assert docx_to_text(body.encode()) == "Hello wide world"


def test_table_rows_become_lines_with_cells_separated_by_bars():
    cell = "<w:tc>{}</w:tc>"
    body = document_xml(
        "<w:tbl>"
        f"<w:tr>{cell.format(paragraph('Name'))}{cell.format(paragraph('Value'))}</w:tr>"
        f"<w:tr>{cell.format(paragraph('port'))}{cell.format(paragraph('8765'))}</w:tr>"
        "</w:tbl>"
    )

    assert docx_to_text(body.encode()) == "Name | Value\n\nport | 8765"


def test_paragraphs_that_look_like_headings_are_escaped():
    body = document_xml(paragraph("# 1 rule"), paragraph("#hashtag"))

    assert docx_to_text(body.encode()) == "\\# 1 rule\n\n#hashtag"


def test_loader_reads_the_text_and_the_title(tmp_path):
    path = write_docx(
        tmp_path / "guide.docx", document_xml(paragraph("Setup", "Ttulo1"), paragraph("Hi"))
    )

    document = DocxLoader().load(path)

    assert document.source == str(path)
    assert document.text == "# Setup\n\nHi"
    assert document.metadata == {"type": "docx", "title": "Install guide"}


def test_loader_without_core_properties_has_no_title(tmp_path):
    path = write_docx(tmp_path / "a.docx", document_xml(paragraph("Hi")), core=None)

    assert DocxLoader().load(path).metadata == {"type": "docx"}


def test_loader_supports_only_docx(tmp_path):
    loader = DocxLoader()

    assert loader.supports(tmp_path / "a.DOCX")
    assert not loader.supports(tmp_path / "a.doc")


def test_loader_rejects_files_that_are_not_docx(tmp_path):
    broken = tmp_path / "broken.docx"
    broken.write_text("not a zip", encoding="utf-8")
    empty = tmp_path / "empty.docx"
    with zipfile.ZipFile(empty, "w") as archive:
        archive.writestr("other.xml", "<x/>")

    with pytest.raises(ValueError, match="not a valid"):
        DocxLoader().load(broken)
    with pytest.raises(ValueError, match="word/document.xml"):
        DocxLoader().load(empty)


def test_loaded_documents_split_on_their_headings(tmp_path):
    path = write_docx(
        tmp_path / "guide.docx",
        document_xml(
            paragraph("Setup", "Ttulo1"),
            paragraph("Install the package."),
            paragraph("Upgrade", "Ttulo2"),
            paragraph("Run the upgrade."),
        ),
    )

    chunks = MarkdownChunker(SlidingWindowChunker(50, 10)).split(DocxLoader().load(path))

    assert [chunk.citation for chunk in chunks] == [
        f"{path}, Setup",
        f"{path}, Setup > Upgrade",
    ]
