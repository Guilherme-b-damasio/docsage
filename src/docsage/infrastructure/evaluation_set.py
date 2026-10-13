"""Reads a labeled query set for retrieval evaluation from a JSON file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docsage.domain.models import EvaluationCase


class EvaluationSetError(ValueError):
    """Raised when the labeled query file is missing or malformed."""


def read_evaluation_set(path: Path) -> list[EvaluationCase]:
    """Returns the cases in ``path``.

    The file holds a list of ``{"query": ..., "relevant": [...]}`` objects, either at the
    top level or under a ``"cases"`` key. ``relevant`` lists the sources that answer the
    query, as full paths or path suffixes such as ``docs/install.md``.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EvaluationSetError(f"Evaluation set not found: {path}") from error
    except json.JSONDecodeError as error:
        raise EvaluationSetError(f"Invalid JSON in {path}: {error}") from error
    items = raw.get("cases") if isinstance(raw, dict) else raw
    if not isinstance(items, list) or not items:
        raise EvaluationSetError(f"{path} must hold a non-empty list of cases")
    return [_case(item, number, path) for number, item in enumerate(items, start=1)]


def _case(item: Any, number: int, path: Path) -> EvaluationCase:
    if not isinstance(item, dict):
        raise EvaluationSetError(f"Case {number} in {path} must be an object")
    query, relevant = item.get("query"), item.get("relevant")
    if not isinstance(query, str) or not query.strip():
        raise EvaluationSetError(f"Case {number} in {path} needs a non-empty query")
    if isinstance(relevant, str):
        relevant = [relevant]
    if (
        not isinstance(relevant, list)
        or not relevant
        or not all(isinstance(source, str) and source.strip() for source in relevant)
    ):
        raise EvaluationSetError(
            f"Case {number} in {path} needs relevant: a non-empty list of sources"
        )
    return EvaluationCase(query.strip(), tuple(source.strip() for source in relevant))
