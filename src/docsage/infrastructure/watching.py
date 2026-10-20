"""File watching by polling: portable and dependency-free, at the cost of a short delay."""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path

from docsage.domain.models import FileChanges

Snapshot = dict[Path, tuple[int, int]]
"""Each file's modification time (ns) and size."""


class PollingWatcher:
    """Looks at the watched folders every ``interval`` seconds and reports what changed.

    A file counts as changed when its modification time or size differs from the last
    look. Files under ``ignore`` (e.g. the index's own folder) are never reported, unless
    that folder holds the watched root itself (an index kept next to the documents).
    """

    def __init__(
        self,
        interval: float = 1.0,
        ignore: Sequence[Path] = (),
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        self._interval = interval
        self._ignore = tuple(path.resolve() for path in ignore)
        self._sleep = sleep

    def watch(self, roots: Sequence[Path]) -> Iterator[FileChanges]:
        previous: Snapshot = {}
        first = True
        while True:
            if not first:
                self._sleep(self._interval)
            current = self.snapshot(roots)
            changes = diff(previous, current)
            if changes or first:
                yield changes
            previous, first = current, False

    def snapshot(self, roots: Sequence[Path]) -> Snapshot:
        files: Snapshot = {}
        for root in roots:
            ignore = self._ignore_under(root)
            candidates = sorted(root.rglob("*")) if root.is_dir() else [root]
            for path in candidates:
                if _ignored(path, ignore):
                    continue
                try:
                    stat = path.stat()
                except OSError:  # deleted between listing and stat
                    continue
                if path.is_file():
                    files[path] = (stat.st_mtime_ns, stat.st_size)
        return files

    def _ignore_under(self, root: Path) -> tuple[Path, ...]:
        """The ignored folders that apply below ``root``: not those that contain it."""
        resolved = root.resolve()
        return tuple(
            folder
            for folder in self._ignore
            if not (resolved == folder or folder in resolved.parents)
        )


def _ignored(path: Path, ignore: tuple[Path, ...]) -> bool:
    if not ignore:
        return False
    resolved = path.resolve()
    return any(resolved == folder or folder in resolved.parents for folder in ignore)


def diff(previous: Snapshot, current: Snapshot) -> FileChanges:
    changed = sorted(path for path, state in current.items() if previous.get(path) != state)
    removed = sorted(path for path in previous if path not in current)
    return FileChanges(tuple(changed), tuple(removed))
