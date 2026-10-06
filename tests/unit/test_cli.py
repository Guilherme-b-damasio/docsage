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
