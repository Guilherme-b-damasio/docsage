"""Path handling shared by the CLI and the MCP server."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path


def expand_paths(paths: Iterable[Path]) -> Iterator[Path]:
    """Yields each file in ``paths``, walking folders recursively in sorted order."""
    for path in paths:
        if path.is_dir():
            yield from sorted(p for p in path.rglob("*") if p.is_file())
        else:
            yield path
