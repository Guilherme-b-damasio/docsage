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
