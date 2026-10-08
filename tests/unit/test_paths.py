from docsage.interfaces.paths import expand_paths


def test_expands_folders_recursively_in_sorted_order(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.md").write_text("b", encoding="utf-8")
    (tmp_path / "a.md").write_text("a", encoding="utf-8")
    single = tmp_path / "single.txt"
    single.write_text("s", encoding="utf-8")

    expanded = list(expand_paths([tmp_path / "sub", tmp_path / "a.md"]))

    assert expanded == [tmp_path / "sub" / "b.md", tmp_path / "a.md"]
    assert list(expand_paths([single])) == [single]
