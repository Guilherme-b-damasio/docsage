"""Loads Word ``.docx`` files as Markdown-like text: headings kept as ``#`` lines.

A ``.docx`` file is a zip of XML parts, so only the standard library is needed. Heading
paragraphs (styles such as "heading 1", "Title" or any style with an outline level)
become Markdown headings, which lets the Markdown chunker split the document on its
sections and cite them as ``report.docx, Setup > Install``. Table rows become lines
with their cells separated by `` | ``.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from docsage.domain.models import Document

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
DC = "{http://purl.org/dc/elements/1.1/}"

DOCUMENT_PART = "word/document.xml"
STYLES_PART = "word/styles.xml"
CORE_PART = "docProps/core.xml"

MAX_HEADING_LEVEL = 6

_SPACES = re.compile(r"\s+")
_LOOKS_LIKE_HEADING = re.compile(r"^#{1,6}[ \t]")
_HEADING_NAME = re.compile(r"^heading\s*([1-9])$", re.IGNORECASE)


class DocxLoader:
    """Loads ``.docx`` documents; the core-properties title goes into the metadata."""

    EXTENSIONS = frozenset({".docx"})

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.EXTENSIONS

    def load(self, path: Path) -> Document:
        try:
            with zipfile.ZipFile(path) as archive:
                parts = set(archive.namelist())
                if DOCUMENT_PART not in parts:
                    raise ValueError(f"{path} has no {DOCUMENT_PART}")
                body = archive.read(DOCUMENT_PART)
                styles = archive.read(STYLES_PART) if STYLES_PART in parts else None
                core = archive.read(CORE_PART) if CORE_PART in parts else None
        except zipfile.BadZipFile as error:
            raise ValueError(f"{path} is not a valid .docx file") from error
        text = docx_to_text(body, styles)
        metadata = {"type": "docx"}
        title = core_title(core) if core else ""
        if title:
            metadata["title"] = title
        return Document(source=str(path), text=text, metadata=metadata)


def docx_to_text(document_xml: bytes, styles_xml: bytes | None = None) -> str:
    """Returns the text of a ``word/document.xml`` part as Markdown-like text."""
    levels = heading_levels(styles_xml) if styles_xml else {}
    body = ElementTree.fromstring(document_xml).find(f"{W}body")
    if body is None:
        return ""
    blocks: list[str] = []
    for element in body:
        if element.tag == f"{W}p":
            block = _paragraph_block(element, levels)
            if block:
                blocks.append(block)
        elif element.tag == f"{W}tbl":
            blocks.extend(_table_rows(element))
    return "\n\n".join(blocks)


def heading_levels(styles_xml: bytes) -> dict[str, int]:
    """Maps each paragraph style id that marks a heading to its level (1-6).

    Style ids are localized ("Ttulo1" in a Portuguese Word), so the level comes from
    the style's English name or its outline level, following ``basedOn`` links.
    """
    styles: dict[str, tuple[int | None, str | None]] = {}
    for style in ElementTree.fromstring(styles_xml).iter(f"{W}style"):
        if style.get(f"{W}type") != "paragraph":
            continue
        style_id = style.get(f"{W}styleId")
        if not style_id:
            continue
        name = style.find(f"{W}name")
        based_on = style.find(f"{W}basedOn")
        own = _name_level(name.get(f"{W}val", "") if name is not None else "")
        if own is None:
            own = _outline_level(style.find(f"{W}pPr"))
        styles[style_id] = (own, based_on.get(f"{W}val") if based_on is not None else None)

    def resolve(style_id: str) -> int | None:
        seen: set[str] = set()
        current: str | None = style_id
        while current is not None and current in styles and current not in seen:
            seen.add(current)
            level, parent = styles[current]
            if level is not None:
                return level
            current = parent
        return None

    levels = {style_id: resolve(style_id) for style_id in styles}
    return {style_id: level for style_id, level in levels.items() if level is not None}


def core_title(core_xml: bytes) -> str:
    """The ``dc:title`` of a ``docProps/core.xml`` part, or ``""``."""
    title = ElementTree.fromstring(core_xml).find(f"{DC}title")
    return _collapse(title.text or "") if title is not None else ""


def _paragraph_block(paragraph: ElementTree.Element, levels: dict[str, int]) -> str:
    text = _collapse(_runs_text(paragraph))
    if not text:
        return ""
    level = _paragraph_level(paragraph, levels)
    if level is not None:
        return f"{'#' * level} {text}"
    # A paragraph such as "# 1 rule" must not turn into a heading.
    return "\\" + text if _LOOKS_LIKE_HEADING.match(text) else text


def _paragraph_level(paragraph: ElementTree.Element, levels: dict[str, int]) -> int | None:
    properties = paragraph.find(f"{W}pPr")
    if properties is None:
        return None
    own = _outline_level(properties)
    if own is not None:
        return own
    style = properties.find(f"{W}pStyle")
    if style is None:
        return None
    style_id = style.get(f"{W}val", "")
    return levels.get(style_id, _name_level(style_id))


def _table_rows(table: ElementTree.Element) -> list[str]:
    rows: list[str] = []
    for row in table.iter(f"{W}tr"):
        cells = [
            _collapse(" ".join(_runs_text(p) for p in cell.iter(f"{W}p")))
            for cell in row.findall(f"{W}tc")
        ]
        line = " | ".join(cell for cell in cells if cell)
        if line:
            rows.append("\\" + line if _LOOKS_LIKE_HEADING.match(line) else line)
    return rows


def _runs_text(paragraph: ElementTree.Element) -> str:
    pieces: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{W}t":
            pieces.append(node.text or "")
        elif node.tag in (f"{W}tab", f"{W}br", f"{W}cr"):
            pieces.append(" ")
    return "".join(pieces)


def _name_level(name: str) -> int | None:
    if name.strip().lower() == "title":
        return 1
    match = _HEADING_NAME.match(name.strip())
    return min(int(match.group(1)), MAX_HEADING_LEVEL) if match else None


def _outline_level(properties: ElementTree.Element | None) -> int | None:
    if properties is None:
        return None
    outline = properties.find(f"{W}outlineLvl")
    if outline is None:
        return None
    try:
        level = int(outline.get(f"{W}val", ""))
    except ValueError:
        return None
    # Level 9 means "body text"; 0-8 are heading levels 1-9.
    return min(level + 1, MAX_HEADING_LEVEL) if 0 <= level < 9 else None


def _collapse(text: str) -> str:
    return _SPACES.sub(" ", text).strip()
