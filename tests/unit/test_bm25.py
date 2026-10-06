from docsage.domain.models import Chunk
from docsage.infrastructure.bm25 import BM25Retriever, JsonIndexRepository, tokenize


def _chunk(id_: str, text: str) -> Chunk:
    return Chunk(id=id_, source=f"{id_}.txt", text=text, position=0)


def _retriever() -> BM25Retriever:
    retriever = BM25Retriever()
    retriever.add(
        [
            _chunk("cats", "Cats are small carnivorous mammals that purr."),
            _chunk("dogs", "Dogs are loyal companions and love to fetch."),
            _chunk("python", "Python is a programming language for data and AI."),
        ]
    )
    return retriever


def test_tokenize_lowercases_and_strips_punctuation():
    assert tokenize("Hello, World! Ação") == ["hello", "world", "ação"]


def test_search_ranks_relevant_chunk_first():
    results = _retriever().search("which language is used for AI?", top_k=3)
    assert results[0].chunk.id == "python"


def test_search_without_matches_returns_empty():
    assert _retriever().search("quantum chromodynamics", top_k=3) == []


def test_re_adding_chunk_replaces_it():
    retriever = _retriever()
    retriever.add([_chunk("cats", "Cats now talk about rockets.")])
    assert len(retriever) == 3
    assert retriever.search("rockets", top_k=1)[0].chunk.id == "cats"
    assert retriever.search("purr", top_k=1) == []


def test_remove_drops_all_chunks_of_a_source():
    retriever = _retriever()
    retriever.add([Chunk(id="cats-1", source="cats.txt", text="Cats sleep a lot.", position=1)])

    assert retriever.remove("cats.txt") == 2
    assert len(retriever) == 2
    assert retriever.search("cats", top_k=3) == []
    assert retriever.search("fetch", top_k=1)[0].chunk.id == "dogs"


def test_remove_unknown_source_is_a_no_op():
    retriever = _retriever()
    assert retriever.remove("missing.txt") == 0
    assert len(retriever) == 3


def test_repository_round_trip(tmp_path):
    repository = JsonIndexRepository(tmp_path / "index.json")
    repository.save(_retriever())
    restored = repository.load()
    assert len(restored) == 3
    assert restored.search("fetch", top_k=1)[0].chunk.id == "dogs"


def test_loading_missing_index_returns_empty_retriever(tmp_path):
    assert len(JsonIndexRepository(tmp_path / "missing.json").load()) == 0


def test_repository_keeps_content_hash_and_reads_old_indexes(tmp_path):
    path = tmp_path / "index.json"
    retriever = BM25Retriever()
    retriever.add([Chunk(id="a", source="a.txt", text="alpha", position=0, content_hash="abc")])
    JsonIndexRepository(path).save(retriever)
    assert JsonIndexRepository(path).load().chunks()[0].content_hash == "abc"

    path.write_text(
        '{"version": 1, "chunks": [{"id": "a", "source": "a.txt", "text": "x", "position": 0}]}',
        encoding="utf-8",
    )
    assert JsonIndexRepository(path).load().chunks()[0].content_hash == ""
