"""Finds query terms in passages so citations can highlight what matched."""

from __future__ import annotations

import re

from docsage.domain.models import Highlight
from docsage.domain.ports import TextTokenizer

_WORD = re.compile(r"\w+", re.UNICODE)


class TermHighlighter:
    """Marks every word of a passage that normalizes to one of the query's terms.

    Words are normalized with the same tokenizer the retriever ranks with, so a span is
    highlighted exactly when it contributed to the BM25 score: case is ignored and
    stopwords in the query never match.
    """

    def __init__(self, tokenizer: TextTokenizer) -> None:
        self._tokenizer = tokenizer

    def highlight(self, query: str, text: str) -> list[Highlight]:
        terms = set(self._tokenizer(query))
        if not terms:
            return []
        highlights = []
        for match in _WORD.finditer(text):
            term = next((token for token in self._tokenizer(match.group()) if token in terms), None)
            if term is not None:
                highlights.append(Highlight(match.start(), match.end(), term))
        return highlights
