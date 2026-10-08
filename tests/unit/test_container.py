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
