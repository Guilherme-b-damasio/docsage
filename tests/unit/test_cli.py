import json

from docsage.interfaces.cli import main


def test_remove_command_drops_indexed_file(tmp_path, capsys):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")
    (tmp_path / "b.md").write_text("beta notes", encoding="utf-8")
    assert main(["--index", str(index), "index", str(tmp_path)]) == 0

    assert main(["--index", str(index), "remove", str(tmp_path / "a.md")]) == 0
    assert "Removed 1 documents (1 chunks)." in capsys.readouterr().out

    assert main(["--index", str(index), "search", "alpha"]) == 1
    assert main(["--index", str(index), "search", "beta"]) == 0


def test_remove_command_reports_missing_path(tmp_path, capsys):
    index = tmp_path / "index.json"
    assert main(["--index", str(index), "remove", str(tmp_path / "nope.md")]) == 1
    assert "Nothing indexed under" in capsys.readouterr().err


def test_index_command_skips_unchanged_files_unless_forced(tmp_path, capsys):
    index = tmp_path / ".docsage" / "index.json"
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("alpha notes", encoding="utf-8")
    main(["--index", str(index), "index", str(docs)])
    capsys.readouterr()

    main(["--index", str(index), "index", str(docs)])
    out = capsys.readouterr().out
    assert "Indexed 0 documents" in out
    assert "Skipped 1 unchanged documents" in out

    main(["--index", str(index), "index", "--force", str(docs)])
    assert "Indexed 1 documents" in capsys.readouterr().out


def test_search_ignores_stopwords(tmp_path):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("The capital of France is Paris.", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path / "a.md")])

    assert main(["--index", str(index), "search", "what is the"]) == 1
    assert main(["--index", str(index), "search", "qual é a capital"]) == 0


def test_search_json_output(tmp_path, capsys):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path)])
    capsys.readouterr()

    assert main(["--index", str(index), "search", "alpha", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["query"] == "alpha"
    assert payload["results"][0]["chunk"]["source"].endswith("a.md")

    assert main(["--index", str(index), "search", "missing", "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["results"] == []


def test_ask_json_output(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    index = tmp_path / "index.json"
    # Empty index: the service answers without calling the generator.
    assert main(["--index", str(index), "ask", "anything?", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "question": "anything?",
        "answer": "No relevant context found in the index.",
        "sources": [],
    }


def test_config_file_sets_index_path(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "docsage.toml").write_text('index_path = "store/idx.json"\n', encoding="utf-8")
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")

    assert main(["index", "a.md"]) == 0
    assert (tmp_path / "store" / "idx.json").is_file()
    assert main(["search", "alpha"]) == 0


def test_index_flag_overrides_config_file(tmp_path, capsys):
    config = tmp_path / "custom.toml"
    config.write_text('index_path = "from-config.json"\n', encoding="utf-8")
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")
    index = tmp_path / "from-flag.json"

    main(["--config", str(config), "--index", str(index), "index", str(tmp_path / "a.md")])

    assert index.is_file()
    assert not (tmp_path / "from-config.json").exists()


def test_invalid_config_file_is_reported(tmp_path, capsys):
    config = tmp_path / "bad.toml"
    config.write_text("chunk_size = 'big'\n", encoding="utf-8")

    assert main(["--config", str(config), "search", "x"]) == 2
    assert "chunk_size" in capsys.readouterr().err


def test_stats_command(tmp_path, capsys):
    index = tmp_path / "index.json"
    (tmp_path / "a.md").write_text("alpha alpha beta", encoding="utf-8")
    (tmp_path / "b.md").write_text("alpha gamma", encoding="utf-8")
    main(["--index", str(index), "index", str(tmp_path)])
    capsys.readouterr()

    assert main(["--index", str(index), "stats", "--top", "1"]) == 0
    out = capsys.readouterr().out
    assert "Documents:  2" in out
    assert "Terms:      5 (3 distinct)" in out
    assert "alpha  3" in out
    assert "beta" not in out

    assert main(["--index", str(index), "stats", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["chunks"] == 2
    assert payload["top_terms"][0] == {"term": "alpha", "count": 3}
    assert payload["index_bytes"] == index.stat().st_size


def test_stats_on_empty_index(tmp_path, capsys):
    assert main(["--index", str(tmp_path / "none.json"), "stats"]) == 0
    out = capsys.readouterr().out
    assert "Documents:  0" in out
    assert "Index size: 0 B" in out


def test_search_cites_the_markdown_section(tmp_path, capsys):
    index = tmp_path / "index.json"
    guide = tmp_path / "guide.md"
    guide.write_text("# Guide\n\n## Install\n\nRun pip install docsage.\n", encoding="utf-8")
    main(["--index", str(index), "index", str(guide)])
    capsys.readouterr()

    assert main(["--index", str(index), "search", "pip"]) == 0
    assert f"{guide}, Guide > Install" in capsys.readouterr().out
