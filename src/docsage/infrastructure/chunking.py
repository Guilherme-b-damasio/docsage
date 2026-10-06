"""Chunking strategies."""

from __future__ import annotations

import hashlib

from docsage.domain.models import Chunk, Document


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
        words = document.text.split()
        chunks: list[Chunk] = []
        for position, start in enumerate(range(0, len(words), self._step)):
            window = words[start : start + self._size]
            if not window:
                break
            text = " ".join(window)
            chunks.append(
                Chunk(
                    id=_chunk_id(document.source, position),
                    source=document.source,
                    text=text,
                    position=position,
                )
            )
            if start + self._size >= len(words):
                break
        return chunks


def _chunk_id(source: str, position: int) -> str:
    digest = hashlib.sha1(source.encode("utf-8")).hexdigest()[:10]
    return f"{digest}-{position}"
