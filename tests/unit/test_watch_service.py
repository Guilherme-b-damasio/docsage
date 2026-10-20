import copy
from itertools import islice
from pathlib import Path

from docsage.application.services import (
    IndexingService,
    LiveWatchService,
    RemovalService,
    WatchService,
)
from docsage.domain.models import FileChanges
from docsage.infrastructure.bm25 import BM25Retriever
from docsage.infrastructure.chunking import SlidingWindowChunker
from docsage.infrastructure.loaders import PlainTextLoader


class InMemoryRepository:
    def __init__(self):
        self.saves = 0

    def save(self, retriever):
        self.saves += 1

    def load(self):
        return BM25Retriever()

    def size_bytes(self):
        return 0


class ScriptedWatcher:
    """Replays prepared batches, running each batch's setup right before yielding it."""

    def __init__(self, batches):
        self._batches = batches
        self.roots = None

    def watch(self, roots):
        self.roots = list(roots)
        for setup, changes in self._batches:
            setup()
            yield changes


def _service(watcher):
    retriever = BM25Retriever()
    repository = InMemoryRepository()
    indexing = IndexingService([PlainTextLoader()], SlidingWindowChunker(), retriever, repository)
    removal = RemovalService(retriever, repository)
    return WatchService(indexing, removal, watcher), retriever, repository


def _sources(retriever):
    return sorted({chunk.source for chunk in retriever.chunks()})


def test_watch_indexes_changed_files_and_drops_deleted_ones(tmp_path: Path):
    a, b = tmp_path / "a.md", tmp_path / "b.md"
    a.write_text("alpha", encoding="utf-8")
    watcher = ScriptedWatcher(
        [
            (lambda: None, FileChanges(changed=(a,))),
            (lambda: b.write_text("beta", encoding="utf-8"), FileChanges(changed=(b,))),
            (lambda: a.unlink(), FileChanges(removed=(a,))),
        ]
    )
    service, retriever, _ = _service(watcher)
    updates = service.watch([tmp_path])

    first = next(updates)
    assert first.indexing.documents == 1 and first
    assert _sources(retriever) == [str(a)]

    next(updates)
    assert _sources(retriever) == [str(a), str(b)]

    last = next(updates)
    assert last.removed == (str(a),) and last.removed_chunks == 1
    assert _sources(retriever) == [str(b)]
    assert watcher.roots == [tmp_path]


def test_unchanged_content_leaves_the_index_alone(tmp_path: Path):
    a = tmp_path / "a.md"
    a.write_text("alpha", encoding="utf-8")
    batch = FileChanges(changed=(a,))
    service, _, repository = _service(ScriptedWatcher([(lambda: None, batch)] * 2))

    first, second = islice(service.watch([tmp_path]), 2)

    assert first and not second
    assert second.indexing.unchanged == 1
    assert repository.saves == 1


def test_deleting_a_file_that_was_never_indexed_changes_nothing(tmp_path: Path):
    service, _, repository = _service(ScriptedWatcher([]))

    update = service.apply(FileChanges(removed=(tmp_path / "image.png",)))

    assert not update
    assert update.removed == ()
    assert repository.saves == 0


def test_unsupported_files_are_reported_as_skipped(tmp_path: Path):
    image = tmp_path / "image.png"
    image.write_bytes(b"\x89PNG")
    service, _, _ = _service(ScriptedWatcher([]))

    update = service.apply(FileChanges(changed=(image,)))

    assert update.indexing.skipped == (str(image),)
    assert not update


class DiskRepository:
    """Keeps a saved copy, like a file on disk: every load starts from the last save."""

    def __init__(self):
        self._saved = BM25Retriever()

    def save(self, retriever):
        self._saved = copy.deepcopy(retriever)

    def load(self):
        return copy.deepcopy(self._saved)

    def size_bytes(self):
        return 0


def _indexing(repository, retriever):
    return IndexingService([PlainTextLoader()], SlidingWindowChunker(), retriever, repository)


def _live(watcher, repository, guard=None):
    def applier():
        retriever = repository.load()
        return WatchService(
            _indexing(repository, retriever), RemovalService(retriever, repository), watcher
        )

    return LiveWatchService(watcher, applier, guard)


def test_live_watch_keeps_what_others_wrote_between_batches(tmp_path: Path):
    a, b, c = (tmp_path / name for name in ("a.md", "b.md", "c.md"))
    for path, text in ((a, "alpha"), (b, "beta"), (c, "gamma")):
        path.write_text(text, encoding="utf-8")
    repository = DiskRepository()

    def another_writer_indexes_b():
        _indexing(repository, repository.load()).index([b])

    watcher = ScriptedWatcher(
        [
            (lambda: None, FileChanges(changed=(a,))),
            (another_writer_indexes_b, FileChanges(changed=(c,))),
        ]
    )

    updates = list(_live(watcher, repository).watch([tmp_path]))

    assert [update.indexing.documents for update in updates] == [1, 1]
    assert _sources(repository.load()) == [str(a), str(b), str(c)]
    assert watcher.roots == [tmp_path]


def test_live_watch_applies_each_batch_inside_the_guard(tmp_path: Path):
    a = tmp_path / "a.md"
    a.write_text("alpha", encoding="utf-8")
    events = []

    class RecordingGuard:
        def __enter__(self):
            events.append("enter")

        def __exit__(self, *exc):
            events.append("exit")
            return False

    repository = DiskRepository()
    watcher = ScriptedWatcher([(lambda: None, FileChanges(changed=(a,)))])
    updates = _live(watcher, repository, RecordingGuard()).watch([tmp_path])

    update = next(updates)

    assert update and events == ["enter", "exit"]
