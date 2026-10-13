import pytest

from docsage.domain.models import Chunk
from docsage.infrastructure.embeddings import (
    CachedEmbedder,
    EmbeddingRetriever,
    SentenceTransformerEmbedder,
)

AXES = ("cat", "dog", "code")


class KeywordEmbedder:
    """Maps each text to keyword counts on a few fixed axes, and records every call."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts):
        self.calls.append(list(texts))
        return [[float(text.lower().count(axis)) for axis in AXES] for text in texts]


def _chunk(id_: str, text: str, source: str | None = None) -> Chunk:
    return Chunk(id=id_, source=source or f"{id_}.txt", text=text, position=0)


def _retriever(embedder: KeywordEmbedder | None = None) -> EmbeddingRetriever:
    retriever = EmbeddingRetriever(embedder or KeywordEmbedder())
    retriever.add(
        [
            _chunk("cats", "A cat purrs; cats nap."),
            _chunk("dogs", "A dog fetches."),
            _chunk("python", "Python code and more code."),
        ]
    )
    return retriever


def test_search_ranks_by_cosine_similarity():
    results = _retriever().search("tell me about cat", top_k=3)

    assert [result.chunk.id for result in results] == ["cats"]
    assert results[0].score == pytest.approx(1.0)
    assert results[0].contributions == ()


def test_search_respects_top_k_and_drops_unrelated_chunks():
    results = _retriever().search("cat and dog", top_k=1)

    assert len(results) == 1
    assert results[0].chunk.id in {"cats", "dogs"}


def test_chunks_are_embedded_lazily_and_only_once():
    embedder = KeywordEmbedder()
    retriever = _retriever(embedder)

    assert retriever.chunks() and embedder.calls == []
    retriever.search("cat", top_k=1)
    retriever.search("dog", top_k=1)

    chunk_batches = [call for call in embedder.calls if len(call) > 1]
    assert chunk_batches == [
        ["A cat purrs; cats nap.", "A dog fetches.", "Python code and more code."]
    ]


def test_re_adding_a_chunk_re_embeds_it():
    retriever = _retriever()
    retriever.search("cat", top_k=1)
    retriever.add([_chunk("cats", "Now about code.")])

    assert len(retriever) == 3
    assert retriever.search("code", top_k=3)[0].chunk.id in {"cats", "python"}
    assert all(result.chunk.id != "cats" for result in retriever.search("cat", top_k=3))


def test_remove_drops_all_chunks_of_a_source():
    retriever = _retriever()
    retriever.add([_chunk("cats-2", "Another cat.", source="cats.txt")])

    assert retriever.remove("cats.txt") == 2
    assert retriever.search("cat", top_k=3) == []
    assert retriever.remove("missing.txt") == 0


def test_empty_query_or_index_returns_nothing():
    assert _retriever().search("   ", top_k=3) == []
    assert EmbeddingRetriever(KeywordEmbedder()).search("cat", top_k=3) == []


class FakeModel:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts, show_progress_bar):
        self.calls.append(texts)
        return [(len(text), 1) for text in texts]


def test_sentence_transformer_embedder_returns_float_lists():
    model = FakeModel()
    embedder = SentenceTransformerEmbedder(model=model)

    assert embedder.embed(["ab", "abc"]) == [[2.0, 1.0], [3.0, 1.0]]
    assert embedder.embed([]) == []
    assert model.calls == [["ab", "abc"]]


def test_sentence_transformer_embedder_explains_the_missing_extra(monkeypatch):
    def missing(name):
        raise ImportError(name)

    monkeypatch.setattr("importlib.import_module", missing)

    with pytest.raises(RuntimeError, match=r"docsage\[embeddings\]"):
        SentenceTransformerEmbedder().embed(["text"])


def test_cached_embedder_only_embeds_unseen_texts_across_instances(tmp_path):
    path = tmp_path / "embeddings.json"
    first = KeywordEmbedder()
    assert CachedEmbedder(first, path, "m").embed(["cat", "dog", "cat"]) == [
        [1.0, 0.0, 0.0],
        [0.0, 1.0, 0.0],
        [1.0, 0.0, 0.0],
    ]
    assert first.calls == [["cat", "dog"]]

    second = KeywordEmbedder()
    vectors = CachedEmbedder(second, path, "m").embed(["dog", "code"])

    assert vectors == [[0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    assert second.calls == [["code"]]


def test_cached_embedder_resets_when_the_model_changes(tmp_path):
    path = tmp_path / "embeddings.json"
    CachedEmbedder(KeywordEmbedder(), path, "old").embed(["cat"])

    embedder = KeywordEmbedder()
    CachedEmbedder(embedder, path, "new").embed(["cat"])

    assert embedder.calls == [["cat"]]
