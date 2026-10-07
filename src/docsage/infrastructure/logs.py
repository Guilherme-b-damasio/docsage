"""Structured logging: one ``key=value`` line per event, written to stderr.

Modules log with the standard library (``logging.getLogger(__name__)``) and pass
event fields through ``extra``; this formatter renders them after the message so
the output stays greppable and easy to parse.
"""

from __future__ import annotations

import logging
import sys
from typing import TextIO

ROOT_LOGGER = "docsage"

# Attributes every LogRecord has; anything else came in through ``extra``.
_RESERVED = frozenset(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class KeyValueFormatter(logging.Formatter):
    """Formats a record as ``level=... logger=... event="..." key=value ...``."""

    def format(self, record: logging.LogRecord) -> str:
        fields: dict[str, object] = {
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        fields.update(
            (key, value) for key, value in vars(record).items() if key not in _RESERVED
        )
        line = " ".join(f"{key}={_quote(value)}" for key, value in fields.items())
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


def _quote(value: object) -> str:
    text = str(value)
    if not text or any(char.isspace() or char in '"=' for char in text):
        return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return text


def configure_logging(verbose: bool = False, stream: TextIO | None = None) -> logging.Logger:
    """Sends ``docsage`` logs to ``stream`` (stderr by default).

    Only warnings are shown unless ``verbose`` is set, which enables debug events.
    Calling it again replaces the previous handler instead of adding another one.
    """
    logger = logging.getLogger(ROOT_LOGGER)
    for handler in list(logger.handlers):
        if getattr(handler, "_docsage", False):
            logger.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(KeyValueFormatter())
    handler._docsage = True  # type: ignore[attr-defined]
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.WARNING)
    return logger
