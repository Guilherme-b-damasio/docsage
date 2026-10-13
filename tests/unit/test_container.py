from pathlib import Path

from docsage.container import DEFAULT_INDEX_PATH, Settings, load_settings


def test_defaults_without_config():
    assert load_settings() == Settings()


def test_config_values_then_overrides(tmp_path):
    config = tmp_path / "docsage.toml"
    config.write_text("chunk_size = 80\nmodel = 'from-config'\n", encoding="utf-8")

    settings = load_settings(config, model="from-flag", index_path=None)

    assert settings.chunk_size == 80
    assert settings.model == "from-flag"
    assert settings.index_path == DEFAULT_INDEX_PATH
    assert isinstance(settings.index_path, Path)


def test_catalog_service_reads_the_configured_index(tmp_path):
    from docsage.container import Container

    service = Container(Settings(index_path=tmp_path / "index.json")).catalog_service()

    assert service.documents() == []


def test_question_answering_uses_an_injected_generator(tmp_path):
    from docsage.container import Container
    from docsage.domain.models import Chunk

    class FakeGenerator:
        def generate(self, question, context):
            return f"{question} -> {len(context)} passages"

    container = Container(Settings(index_path=tmp_path / "index.json"), FakeGenerator())
    notes = tmp_path / "notes.md"
    notes.write_text("Lisbon is the capital of Portugal.", encoding="utf-8")
    container.indexing_service().index([notes])

    answer = container.question_answering_service().ask("Where is Lisbon?")

    assert answer.text == "Where is Lisbon? -> 1 passages"
    assert isinstance(answer.sources[0].chunk, Chunk)


def test_search_results_carry_highlights_from_the_shared_tokenizer(tmp_path):
    from docsage.container import Container

    container = Container(Settings(index_path=tmp_path / "index.json"))
    notes = tmp_path / "notes.md"
    notes.write_text("The Index lives on disk.", encoding="utf-8")
    container.indexing_service().index([notes])

    (result,) = container.search_service().search("where is the index?")

    assert result.matched_terms == ("index",)
    (highlight,) = result.highlights
    assert result.chunk.text[highlight.start : highlight.end] == "Index"


def test_answer_report_service_renders_html_or_text(tmp_path):
    import pytest

    from docsage.container import Container

    class FakeGenerator:
        def generate(self, question, context):
            return "Lisbon [1]."

    container = Container(Settings(index_path=tmp_path / "index.json"), FakeGenerator())
    notes = tmp_path / "notes.md"
    notes.write_text("Lisbon is the capital of Portugal.", encoding="utf-8")
    container.indexing_service().index([notes])

    html = container.answer_report_service().report("Where is Lisbon?")
    text = container.answer_report_service("text").report("Where is Lisbon?")

    assert html.answer.text == "Lisbon [1]."
    assert '<mark title="lisbon">Lisbon</mark>' in html.content
    assert "**Lisbon**" in text.content
    with pytest.raises(ValueError, match="Unknown report format"):
        container.answer_report_service("pdf")


def test_dashboard_service_rejects_unknown_formats(tmp_path):
    import pytest

    from docsage.container import Container

    container = Container(Settings(index_path=tmp_path / "index.json"))

    assert "The index is empty" in container.dashboard_service().render()
    with pytest.raises(ValueError, match="Unknown dashboard format"):
        container.dashboard_service("svg")


class _KeywordEmbedder:
    def __init__(self) -> None:
        self.texts: list[str] = []

    def embed(self, texts):
        self.texts.extend(texts)
        return [[float("lisbon" in text.lower()), float("tokyo" in text.lower())] for text in texts]


def test_embedding_retriever_ranks_with_the_injected_embedder_and_caches_vectors(tmp_path):
    from docsage.container import Container

    settings = Settings(index_path=tmp_path / "index.json", retriever="embedding")
    embedder = _KeywordEmbedder()
    container = Container(settings, embedder=embedder)
    for name, text in [("pt.md", "Lisbon is in Portugal."), ("jp.md", "Tokyo is in Japan.")]:
        (tmp_path / name).write_text(text, encoding="utf-8")
        container.indexing_service().index([tmp_path / name])

    (result,) = container.search_service().search("lisbon", top_k=1)

    assert result.chunk.source.endswith("pt.md")
    assert (tmp_path / "index.embeddings.json").is_file()
    embedder.texts.clear()
    Container(settings, embedder=embedder).search_service().search("tokyo", top_k=1)
    assert embedder.texts == ["tokyo"]


def test_unknown_retriever_is_rejected():
    import pytest

    from docsage.infrastructure.config import ConfigError

    with pytest.raises(ConfigError, match="Unknown retriever"):
        load_settings(retriever="magic")


def test_hybrid_retriever_finds_chunks_either_ranking_misses(tmp_path):
    from docsage.container import Container

    settings = Settings(index_path=tmp_path / "index.json", retriever="hybrid")
    container = Container(settings, embedder=_KeywordEmbedder())
    notes = tmp_path / "notes.md"
    notes.write_text("# Lisbon\n\nCapital of Portugal.\n\n# Japan\n\nIts capital.\n", "utf-8")
    container.indexing_service().index([notes])

    results = container.search_service().search("lisbon capital", top_k=2)

    assert len(results) == 2
    assert results[0].chunk.section == "Lisbon"
    assert results[0].contributions == ()
