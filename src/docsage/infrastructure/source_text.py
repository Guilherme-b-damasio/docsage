"""Reads an indexed document's text back with the loaders that indexed it."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from pathlib import Path

from docsage.domain.models import is_url
from docsage.domain.ports import DocumentLoader

logger = logging.getLogger(__name__)


class LoaderSourceTextReader:
    """A ``SourceTextReader`` over the document loaders, for sources still on this machine.

    Web pages are not fetched again, formats no loader reads and files that are gone or
    unreadable come back as None, so a caller can fall back to linking the source instead
    of inlining it.
    """

    def __init__(self, loaders: Sequence[DocumentLoader]) -> None:
        self._loaders = list(loaders)

    def text(self, source: str) -> str | None:
        if is_url(source):
            return None
        path = Path(source)
        for loader in self._loaders:
            if not loader.supports(path):
                continue
            try:
                return loader.load(path).text
            except (OSError, ValueError) as error:
                logger.debug(
                    "could not read a source back",
                    extra={"source": source, "error": str(error)},
                )
                return None
        return None
