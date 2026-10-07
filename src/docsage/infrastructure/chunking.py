"""Chunking strategies."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace

from docsage.domain.models import Chunk, Document
from docsage.domain.ports import Chunker


class SlidingWindowChunker:
    """Splits text into overlapping windows of words.

    Overlap keeps sentences that straddle a boundary retrievable from either side.
    """

    def __init__(self, size: int = 200, overlap: int = 40) -> None:
        if size <= 0:
            raise ValueError("size must be positive")
        if not 0 <= overlap < size:
            raise ValueError("overlap must be in [0, size)")
        self._size = size
        self._step = size - overlap

    def split(self, document: Document) -> list[Chunk]:
        matches = list(_WORD.finditer(document.text))
        chunks: list[Chunk] = []
        for position, start in enumerate(range(0, len(matches), self._step)):
            window = matches[start : start + self._size]
            if not window:
                break
            text = " ".join(match.group() for match in window)
            chunks.append(
                Chunk(
                    id=_chunk_id(document.source, position),
                    source=document.source,
                    text=text,
                    position=position,
                    first_page=document.page_at(window[0].start()),
                    last_page=document.page_at(window[-1].start()),
                )
            )
            if start + self._size >= len(matches):
                break
        return chunks


class MarkdownChunker:
    """Splits Markdown on ATX headings and keeps the heading path on each chunk.

    Sections longer than the body chunker's window are split further by it, so a
    chunk never mixes text from two sections. Headings inside fenced code blocks
    are ignored.
    """

    def __init__(self, body_chunker: Chunker | None = None) -> None:
        self._body_chunker = body_chunker or SlidingWindowChunker()

    def split(self, document: Document) -> list[Chunk]:
        chunks: list[Chunk] = []
        for section, text in markdown_sections(document.text):
            part = Document(source=document.source, text=text, metadata=document.metadata)
            for chunk in self._body_chunker.split(part):
                position = len(chunks)
                chunks.append(
                    replace(
                        chunk,
                        id=_chunk_id(document.source, position),
                        position=position,
                        section=section,
                    )
                )
        return chunks


def markdown_sections(text: str) -> list[tuple[str, str]]:
    """Returns ``(heading path, section text)`` pairs in document order.

    Each section's text starts with its own heading line. Sections that hold
    nothing but their heading are dropped; their title survives in the path of
    the subsections below them.
    """
    raw: list[tuple[str, list[str], bool]] = [("", [], False)]
    path: list[tuple[int, str]] = []
    fence: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if fence is None and (match := _HEADING.match(line)):
            level, title = len(match.group(1)), match.group(2)
            path = [entry for entry in path if entry[0] < level] + [(level, title)]
            raw.append((" > ".join(title for _, title in path), [line], False))
            continue
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = marker if fence is None else (None if marker == fence else fence)
        section, lines, has_body = raw[-1]
        lines.append(line)
        raw[-1] = (section, lines, has_body or bool(stripped))
    return [(section, "\n".join(lines)) for section, lines, has_body in raw if has_body]


_WORD = re.compile(r"\S+")
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")


def _chunk_id(source: str, position: int) -> str:
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:10]
    return f"{digest}-{position}"
