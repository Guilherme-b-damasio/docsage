"""Reads ``docsage.toml`` into plain, validated setting values."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

CONFIG_FILENAME = "docsage.toml"

_FIELD_TYPES: dict[str, type] = {
    "index_path": str,
    "chunk_size": int,
    "chunk_overlap": int,
    "model": str,
}


class ConfigError(ValueError):
    """Raised when the config file is missing, malformed or has invalid values."""


def read_config(path: Path) -> dict[str, Any]:
    """Returns the settings found in ``path``.

    A relative ``index_path`` is resolved against the config file's folder, so the
    same file works no matter where the command is run from.
    """
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except FileNotFoundError as error:
        raise ConfigError(f"Config file not found: {path}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"Invalid TOML in {path}: {error}") from error

    unknown = sorted(set(raw) - set(_FIELD_TYPES))
    if unknown:
        raise ConfigError(f"Unknown keys in {path}: {', '.join(unknown)}")

    values: dict[str, Any] = {}
    for key, value in raw.items():
        expected = _FIELD_TYPES[key]
        # bool is a subclass of int, but `chunk_size = true` is a mistake.
        if not isinstance(value, expected) or isinstance(value, bool):
            raise ConfigError(f"{key} in {path} must be a {expected.__name__}")
        values[key] = value

    if "index_path" in values:
        index_path = Path(values["index_path"])
        values["index_path"] = index_path if index_path.is_absolute() else path.parent / index_path
    return values
