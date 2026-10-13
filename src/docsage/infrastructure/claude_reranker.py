"""Re-ranking backed by the Claude API: the model grades each candidate passage."""

from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from typing import Any

import anthropic
from anthropic.types.beta import BetaMessageParam

from docsage.domain.models import SearchResult
from docsage.infrastructure.claude_generator import DEFAULT_MODEL, Effort

logger = logging.getLogger(__name__)

MAX_RELEVANCE = 10

SYSTEM_PROMPT = (
    "You grade how well numbered passages answer a search query. Give every passage a "
    f"relevance from 0 (unrelated) to {MAX_RELEVANCE} (answers the query directly). "
    "Judge the meaning, not shared words, and grade each passage on its own."
)

RELEVANCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "grades": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "passage": {"type": "integer"},
                    "relevance": {"type": "integer"},
                },
                "required": ["passage", "relevance"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["grades"],
    "additionalProperties": False,
}


class RerankRefusedError(RuntimeError):
    """Raised when the model declines to grade the passages."""


class ClaudeReranker:
    """Asks Claude for a 0-10 relevance grade per candidate and sorts by it.

    Ties keep the first-stage order, and a passage the model leaves out is graded 0,
    so the result always contains every candidate.
    """

    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        model: str = DEFAULT_MODEL,
        effort: Effort = "low",
        max_tokens: int = 16000,
    ) -> None:
        self._client = client or anthropic.Anthropic()
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens

    def rerank(self, query: str, candidates: Sequence[SearchResult]) -> list[SearchResult]:
        if not candidates:
            return []
        message: BetaMessageParam = {"role": "user", "content": build_prompt(query, candidates)}
        response = self._client.beta.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=SYSTEM_PROMPT,
            output_config={
                "effort": self._effort,
                "format": {"type": "json_schema", "schema": RELEVANCE_SCHEMA},
            },
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[message],
        )
        logger.debug(
            "claude rerank response",
            extra={
                "model": response.model,
                "stop_reason": response.stop_reason,
                "candidates": len(candidates),
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        )
        if response.stop_reason == "refusal":
            logger.warning("claude refused to rerank", extra={"model": response.model})
            raise RerankRefusedError("The model declined to grade the passages.")
        text = "".join(block.text for block in response.content if block.type == "text")
        return order_by_grades(candidates, parse_grades(text, len(candidates)))


def build_prompt(query: str, candidates: Sequence[SearchResult]) -> str:
    passages = "\n\n".join(
        f"[{index}] (source: {result.chunk.citation})\n{result.chunk.text}"
        for index, result in enumerate(candidates, start=1)
    )
    return f"<passages>\n{passages}\n</passages>\n\nQuery: {query}"


def parse_grades(text: str, count: int) -> dict[int, int]:
    """Maps 1-based passage numbers to a relevance clamped to ``0..MAX_RELEVANCE``.

    Numbers outside ``1..count`` are ignored; a repeated passage keeps its first grade.
    """
    grades: dict[int, int] = {}
    for grade in json.loads(text)["grades"]:
        passage = grade["passage"]
        if 1 <= passage <= count and passage not in grades:
            grades[passage] = min(max(grade["relevance"], 0), MAX_RELEVANCE)
    return grades


def order_by_grades(
    candidates: Sequence[SearchResult], grades: dict[int, int]
) -> list[SearchResult]:
    graded = [
        (grades.get(index, 0), index, result) for index, result in enumerate(candidates, start=1)
    ]
    graded.sort(key=lambda item: (-item[0], item[1]))
    return [SearchResult(result.chunk, float(grade)) for grade, _, result in graded]
