import pytest

from docsage.infrastructure.config import ConfigError, read_config


def _write(tmp_path, text):
    path = tmp_path / "docsage.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_reads_known_keys(tmp_path):
    path = _write(tmp_path, 'chunk_size = 120\nchunk_overlap = 20\nmodel = "m"\n')

    assert read_config(path) == {"chunk_size": 120, "chunk_overlap": 20, "model": "m"}


def test_relative_index_path_is_resolved_against_the_config_folder(tmp_path):
    path = _write(tmp_path, 'index_path = "data/index.json"\n')

    assert read_config(path)["index_path"] == tmp_path / "data" / "index.json"


def test_absolute_index_path_is_kept(tmp_path):
    target = tmp_path / "elsewhere" / "index.json"
    path = _write(tmp_path, f"index_path = '{target}'\n")

    assert read_config(path)["index_path"] == target


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("chunk_size = 'big'\n", "chunk_size"),
        ("chunk_size = true\n", "chunk_size"),
        ("colour = 'blue'\n", "Unknown keys"),
        ("chunk_size = \n", "Invalid TOML"),
    ],
)
def test_rejects_invalid_files(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message):
        read_config(_write(tmp_path, text))


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        read_config(tmp_path / "nope.toml")
