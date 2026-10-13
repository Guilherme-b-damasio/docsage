"""Dense-vector retrieval: a cosine-similarity retriever, a local embedding model and a cache."""

from __future__ import annotations

import hashlib
import importlib
import json
import logging
import math
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from docsage.domain.models import Chunk, SearchResult
from docsage.domain.ports import Embedder

logger = logging.getLogger(__name__)


class EmbeddingRetriever:
    """Ranks chunks by the cosine similarity of their embedding to the query's.

    Chunks are embedded lazily, on the first search after they were added, so commands
    that only read the chunk list (stats, catalog...) never run the embedding model.
    """

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder
        self._chunks: dict[str, Chunk] = {}
        self._vectors: dict[str, list[float]] = {}

    def add(self, chunks: Iterable[Chunk]) -> None:
        for chunk in chunks:
            self._chunks[chunk.id] = chunk
            self._vectors.pop(chunk.id, None)

    def search(self, query: str, top_k: int) -> list[SearchResult]:
        if not query.strip() or not self._chunks:
            return []
        self._embed_pending()
        (query_vector,) = self._embedder.embed([query])
        scored = [
            SearchResult(chunk, _cosine(query_vector, self._vectors[chunk_id]))
            for chunk_id, chunk in self._chunks.items()
        ]
        scored.sort(key=lambda result: result.score, reverse=True)
        return [result for result in scored if result.score > 0][:top_k]

    def remove(self, source: str) -> int:
        doomed = [chunk_id for chunk_id, chunk in self._chunks.items() if chunk.source == source]
        for chunk_id in doomed:
            del self._chunks[chunk_id]
            self._vectors.pop(chunk_id, None)
        return len(doomed)

    def chunks(self) -> list[Chunk]:
        return list(self._chunks.values())

    def __len__(self) -> int:
        return len(self._chunks)

    def _embed_pending(self) -> None:
        pending = [chunk for chunk in self._chunks.values() if chunk.id not in self._vectors]
        if not pending:
            return
        vectors = self._embedder.embed([chunk.text for chunk in pending])
        self._vectors.update(zip((chunk.id for chunk in pending), vectors, strict=True))
        logger.debug("embedded chunks", extra={"chunks": len(pending)})


def _cosine(first: Sequence[float], second: Sequence[float]) -> float:
    norms = math.sqrt(sum(x * x for x in first)) * math.sqrt(sum(y * y for y in second))
    if not norms:
        return 0.0
    return sum(x * y for x, y in zip(first, second, strict=True)) / norms


DEFAULT_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
"""Small multilingual model, matching the English + Portuguese tokenizer."""


class SentenceTransformerEmbedder:
    """Runs a local sentence-transformers model (``pip install docsage[embeddings]``).

    The model is loaded on the first ``embed`` call, so building the adapter is free.
    """

    def __init__(self, model_name: str = DEFAULT_EMBEDDING_MODEL, model: Any = None) -> None:
        """``model`` replaces the loaded model, e.g. with a fake in tests."""
        self.model_name = model_name
        self._model = model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = self._loaded().encode(list(texts), show_progress_bar=False)
        return [[float(value) for value in vector] for vector in vectors]

    def _loaded(self) -> Any:
        if self._model is None:
            try:
                library = importlib.import_module("sentence_transformers")
            except ImportError as error:
                raise RuntimeError(
                    "Embedding retrieval needs sentence-transformers: "
                    "pip install 'docsage[embeddings]'"
                ) from error
            logger.debug("loading embedding model", extra={"model": self.model_name})
            self._model = library.SentenceTransformer(self.model_name)
        return self._model


class CachedEmbedder:
    """Keeps vectors in a JSON file keyed by text hash, so unchanged chunks are never
    re-embedded across runs. The cache is tied to a model name and reset when it changes.
    """

    def __init__(self, inner: Embedder, path: Path, model_name: str) -> None:
        self._inner = inner
        self._path = path
        self._model_name = model_name
        self._vectors: dict[str, list[float]] | None = None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        vectors = self._cache()
        keys = [_text_key(text) for text in texts]
        missing = list(dict.fromkeys(key for key in keys if key not in vectors))
        if missing:
            text_by_key = dict(zip(keys, texts, strict=True))
            fresh = self._inner.embed([text_by_key[key] for key in missing])
            vectors.update(zip(missing, fresh, strict=True))
            self._write(vectors)
        return [vectors[key] for key in keys]

    def _cache(self) -> dict[str, list[float]]:
        if self._vectors is None:
            self._vectors = {}
            if self._path.exists():
                payload = json.loads(self._path.read_text(encoding="utf-8"))
                if payload.get("model") == self._model_name:
                    self._vectors = payload["vectors"]
        return self._vectors

    def _write(self, vectors: dict[str, list[float]]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "model": self._model_name, "vectors": vectors}
        self._path.write_text(json.dumps(payload), encoding="utf-8")
        logger.debug("saved embedding cache", extra={"path": str(self._path)})


def _text_key(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
