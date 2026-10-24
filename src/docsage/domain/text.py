"""Pure text helpers the domain's consumers share. No I/O and no third-party dependencies."""

from __future__ import annotations

import re


def passage_span(text: str, passage: str) -> tuple[int, int] | None:
    """Where ``passage`` occurs in ``text``, ignoring how its whitespace was normalized.

    Chunkers join a passage's words with single spaces, so a stored chunk seldom appears
    in its document verbatim; its words are matched in order across any whitespace
    instead. Returns None when the passage is blank or cannot be found, e.g. because the
    document changed since it was indexed.
    """
    words = passage.split()
    if not words:
        return None
    pattern = r"\s+".join(re.escape(word) for word in words)
    match = re.search(pattern, text)
    return (match.start(), match.end()) if match else None
