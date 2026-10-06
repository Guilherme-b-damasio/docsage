"""A dependency-free BM25 retriever and its JSON repository."""

from __future__ import annotations

import json
import math
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import asdict
from pathlib import Path

from docsage.domain.models import Chunk, SearchResult
from docsage.domain.ports import Retriever
from docsage.infrastructure.tokenizer import Tokenizer

tokenize = Tokenizer()


class BM25Retriever:
    """Okapi BM25 ranking over an in-memory set of chunks."""

    def __init__(
        self,
        k1: float = 1.5,
        b: float = 0.75,
        tokenizer: Callable[[str], list[str]] = tokenize,
    ) -> None:
        self._k1 = k1
        self._b = b
        self._tokenize = tokenizer
        self._chunks: dict[str, Chunk] = {}
        self._term_freqs: dict[str, Counter[str]] = {}
        self._doc_freq: Counter[str] = Counter()

    def add(self, chunks: Iterable[Chunk]) -> None:
        for chunk in chunks:
            if chunk.id in self._chunks:
                self._remove(chunk.id)
            freqs = Counter(self._tokenize(chunk.text))
            self._chunks[chunk.id] = chunk
            self._term_freqs[chunk.id] = freqs
            self._doc_freq.update(freqs.keys())

    def search(self, query: str, top_k: int) -> list[SearchResult]:
        terms = self._tokenize(query)
        if not terms or not self._chunks:
            return []
        avg_len = sum(sum(f.values()) for f in self._term_freqs.values()) / len(self)
        scored: list[SearchResult] = []
        for chunk_id, freqs in self._term_freqs.items():
            score = self._score(terms, freqs, avg_len)
            if score > 0:
                scored.append(SearchResult(self._chunks[chunk_id], score))
        scored.sort(key=lambda result: result.score, reverse=True)
        return scored[:top_k]

    def remove(self, source: str) -> int:
        doomed = [chunk_id for chunk_id, chunk in self._chunks.items() if chunk.source == source]
        for chunk_id in doomed:
            self._remove(chunk_id)
        return len(doomed)

    def chunks(self) -> list[Chunk]:
        return list(self._chunks.values())

    def __len__(self) -> int:
        return len(self._chunks)

    def _score(self, terms: list[str], freqs: Counter[str], avg_len: float) -> float:
        length = sum(freqs.values())
        total = len(self)
        score = 0.0
        for term in terms:
            tf = freqs.get(term, 0)
            if not tf:
                continue
            df = self._doc_freq[term]
            idf = math.log(1 + (total - df + 0.5) / (df + 0.5))
            norm = tf + self._k1 * (1 - self._b + self._b * length / avg_len)
            score += idf * tf * (self._k1 + 1) / norm
        return score

    def _remove(self, chunk_id: str) -> None:
        self._doc_freq.subtract(self._term_freqs.pop(chunk_id).keys())
        self._doc_freq += Counter()  # drop zero counts
        del self._chunks[chunk_id]


class JsonIndexRepository:
    """Stores the chunk set as JSON; term statistics are rebuilt on load."""

    def __init__(
        self, path: Path, retriever_factory: Callable[[], BM25Retriever] = BM25Retriever
    ) -> None:
        self._path = path
        self._retriever_factory = retriever_factory

    def save(self, retriever: Retriever) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "chunks": [asdict(c) for c in retriever.chunks()]}
        self._path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def size_bytes(self) -> int:
        return self._path.stat().st_size if self._path.exists() else 0

    def load(self) -> BM25Retriever:
        retriever = self._retriever_factory()
        if self._path.exists():
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            retriever.add(Chunk(**raw) for raw in payload["chunks"])
        return retriever
