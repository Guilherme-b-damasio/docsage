"""Tokenization for lexical retrieval, with optional stopword filtering."""

from __future__ import annotations

import re
from collections.abc import Iterable

_TOKEN = re.compile(r"\w+", re.UNICODE)

ENGLISH_STOPWORDS = frozenset(
    """
    a about above after again against all am an and any are as at be because been before
    being below between both but by can could did do does doing down during each few for
    from further had has have having he her here hers herself him himself his how i if in
    into is it its itself just me more most my myself no nor not now of off on once only
    or other our ours ourselves out over own same she should so some such than that the
    their theirs them themselves then there these they this those through to too under
    until up very was we were what when where which while who whom why will with would you
    your yours yourself yourselves
    """.split()
)

PORTUGUESE_STOPWORDS = frozenset(
    """
    a ao aos aquela aquelas aquele aqueles aquilo as até com como da das de dela delas dele
    deles depois do dos e ela elas ele eles em entre era eram essa essas esse esses esta
    estas este estes eu foi foram há isso isto já lhe lhes mais mas me mesmo meu meus minha
    minhas muito na nas nem no nos nós num numa o os ou para pela pelas pelo pelos por qual
    quando que quem se sem ser seu seus só sua suas também te tem têm teu tu tua um uma umas
    uns você vocês vos à às é
    """.split()
)


class Tokenizer:
    """Lowercases text, splits it into word tokens and drops the given stopwords."""

    def __init__(self, stopwords: Iterable[str] = ()) -> None:
        self._stopwords = frozenset(word.lower() for word in stopwords)

    def __call__(self, text: str) -> list[str]:
        tokens = (token.lower() for token in _TOKEN.findall(text))
        return [token for token in tokens if token not in self._stopwords]


def multilingual_tokenizer() -> Tokenizer:
    """Tokenizer that ignores common English and Portuguese function words."""
    return Tokenizer(ENGLISH_STOPWORDS | PORTUGUESE_STOPWORDS)
