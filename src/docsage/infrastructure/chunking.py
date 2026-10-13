"""Chunking strategies."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
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


class SentenceChunker:
    """Packs whole sentences into chunks of at most ``size`` words.

    Chunks never end mid-sentence, so a passage handed to the model reads naturally.
    Each chunk repeats the previous chunk's last sentences, up to ``overlap`` words, so a
    thought that spans a boundary stays retrievable from either side. A sentence longer
    than ``size`` words is cut into windows of ``size`` words.
    """

    def __init__(self, size: int = 200, overlap: int = 40) -> None:
        if size <= 0:
            raise ValueError("size must be positive")
        if not 0 <= overlap < size:
            raise ValueError("overlap must be in [0, size)")
        self._size = size
        self._overlap = overlap

    def split(self, document: Document) -> list[Chunk]:
        sentences = [
            piece
            for sentence in sentence_spans(document.text)
            for piece in _windows(sentence, self._size)
        ]
        chunks: list[Chunk] = []
        start = 0
        while start < len(sentences):
            end, words = start, 0
            while end < len(sentences) and words + len(sentences[end]) <= self._size:
                words += len(sentences[end])
                end += 1
            window = [word for sentence in sentences[start:end] for word in sentence]
            chunks.append(
                Chunk(
                    id=_chunk_id(document.source, len(chunks)),
                    source=document.source,
                    text=" ".join(word.group() for word in window),
                    position=len(chunks),
                    first_page=document.page_at(window[0].start()),
                    last_page=document.page_at(window[-1].start()),
                )
            )
            if end == len(sentences):
                break
            start = self._next_start(sentences, start, end)
        return chunks

    def _next_start(self, sentences: list[list[re.Match[str]]], start: int, end: int) -> int:
        """First sentence of the next chunk: this chunk's last sentences that fit in
        ``overlap`` words, but always past ``start`` so the chunker makes progress."""
        next_start, carried = end, 0
        while next_start - 1 > start and carried + len(sentences[next_start - 1]) <= self._overlap:
            next_start -= 1
            carried += len(sentences[next_start])
        return next_start


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


class ChunkerByType:
    """Delegates to a chunker chosen by the document's ``type`` metadata."""

    def __init__(self, chunkers: Mapping[str, Chunker], default: Chunker) -> None:
        self._chunkers = dict(chunkers)
        self._default = default

    def split(self, document: Document) -> list[Chunk]:
        chunker = self._chunkers.get(document.metadata.get("type", ""), self._default)
        return chunker.split(document)


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


def sentence_spans(text: str) -> list[list[re.Match[str]]]:
    """Groups the words of ``text`` into sentences, keeping each word's offsets.

    A sentence ends at a word ending in ``.``, ``!``, ``?`` or ``…`` (closing quotes and
    brackets allowed) unless the word is a common abbreviation or the next word starts in
    lower case. A blank line always ends a sentence, so headings and list items do not
    run into the paragraph that follows them.
    """
    words = list(_WORD.finditer(text))
    sentences: list[list[re.Match[str]]] = []
    current: list[re.Match[str]] = []
    for index, word in enumerate(words):
        current.append(word)
        following = words[index + 1] if index + 1 < len(words) else None
        if following is None or _ends_sentence(text, word, following):
            sentences.append(current)
            current = []
    return sentences


def _ends_sentence(text: str, word: re.Match[str], following: re.Match[str]) -> bool:
    if _BLANK_LINE.search(text, word.end(), following.start()):
        return True
    token = word.group().rstrip(_CLOSERS)
    if not token.endswith(_TERMINATORS):
        return False
    if token.rstrip(".").lower() in _ABBREVIATIONS:
        return False
    return not following.group().lstrip(_OPENERS)[:1].islower()


def _windows(words: list[re.Match[str]], size: int) -> list[list[re.Match[str]]]:
    return [words[start : start + size] for start in range(0, len(words), size)]


_WORD = re.compile(r"\S+")
_BLANK_LINE = re.compile(r"\n[ \t]*\r?\n")
_TERMINATORS = (".", "!", "?", "…")
_CLOSERS = "\"')]}»”’*_"
_OPENERS = "\"'([{«“‘*_"
_ABBREVIATIONS = frozenset(
    "e.g i.e etc vs cf al fig no p pp mr mrs ms dr prof sr sra st jr approx ex".split()
)
_HEADING = re.compile(r"^ {0,3}(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")


def _chunk_id(source: str, position: int) -> str:
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:10]
    return f"{digest}-{position}"
