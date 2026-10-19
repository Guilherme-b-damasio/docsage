import os
from itertools import islice
from pathlib import Path

import pytest

from docsage.domain.models import FileChanges
from docsage.infrastructure.watching import PollingWatcher, diff


def _touch(path: Path, text: str, mtime_ns: int) -> None:
    path.write_text(text, encoding="utf-8")
    os.utime(path, ns=(mtime_ns, mtime_ns))


def test_file_changes_is_falsy_when_empty():
    assert not FileChanges()
    assert FileChanges(removed=(Path("a.md"),))


def test_diff_reports_new_modified_and_deleted_files():
    previous = {Path("a.md"): (1, 10), Path("b.md"): (1, 10), Path("c.md"): (1, 10)}
    current = {Path("a.md"): (1, 10), Path("b.md"): (2, 12), Path("d.md"): (1, 3)}

    changes = diff(previous, current)

    assert changes.changed == (Path("b.md"), Path("d.md"))
    assert changes.removed == (Path("c.md"),)


def test_first_batch_lists_existing_files_even_when_the_folder_is_empty(tmp_path):
    watcher = PollingWatcher(sleep=lambda _: None)

    assert next(watcher.watch([tmp_path])) == FileChanges()

    (tmp_path / "a.md").write_text("alpha", encoding="utf-8")
    assert next(watcher.watch([tmp_path])).changed == (tmp_path / "a.md",)


def test_watch_yields_only_when_something_changed(tmp_path):
    notes = tmp_path / "notes.md"
    _touch(notes, "one", 1_000_000_000)
    steps = iter(
        [
            lambda: None,  # nothing happens: no batch
            lambda: _touch(notes, "one two", 2_000_000_000),
            lambda: notes.unlink(),
        ]
    )
    watcher = PollingWatcher(interval=0.5, sleep=lambda seconds: next(steps)())

    batches = list(islice(watcher.watch([tmp_path]), 3))

    assert batches == [
        FileChanges(changed=(notes,)),
        FileChanges(changed=(notes,)),
        FileChanges(removed=(notes,)),
    ]


def test_watch_sleeps_for_the_interval(tmp_path):
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        (tmp_path / f"{len(slept)}.md").write_text("x", encoding="utf-8")

    watcher = PollingWatcher(interval=2.5, sleep=sleep)
    list(islice(watcher.watch([tmp_path]), 2))

    assert slept == [2.5]


def test_ignored_folders_and_single_files(tmp_path):
    index_dir = tmp_path / ".docsage"
    index_dir.mkdir()
    (index_dir / "index.json").write_text("{}", encoding="utf-8")
    (tmp_path / "a.md").write_text("alpha", encoding="utf-8")
    single = tmp_path / "b.md"
    single.write_text("beta", encoding="utf-8")
    watcher = PollingWatcher(ignore=[index_dir])

    assert sorted(watcher.snapshot([tmp_path])) == [tmp_path / "a.md", single]
    assert list(watcher.snapshot([single])) == [single]
    assert watcher.snapshot([tmp_path / "missing"]) == {}


def test_interval_must_be_positive():
    with pytest.raises(ValueError):
        PollingWatcher(interval=0)
