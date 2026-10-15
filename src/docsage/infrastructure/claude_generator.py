"""Answer generation backed by the Claude API."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from typing import Any, Literal

import anthropic
from anthropic.types.beta import BetaMessage, BetaMessageParam

from docsage.domain.models import SearchResult

DEFAULT_MODEL = "claude-opus-5-5"

Effort = Literal["low", "medium", "high", "xhigh", "max"]

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You answer questions using only the numbered context passages provided. "
    "Cite passages inline as [1], [2], etc. If the context does not contain the "
    "answer, say so plainly instead of guessing. Answer in the language of the question."
)


class GenerationRefusedError(RuntimeError):
    """Raised when the model declines to answer."""


class ClaudeAnswerGenerator:
    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        model: str = DEFAULT_MODEL,
        effort: Effort = "medium",
        max_tokens: int = 16000,
    ) -> None:
        self._client = client or anthropic.Anthropic()
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens

    def generate(self, question: str, context: Sequence[SearchResult]) -> str:
        response = self._client.beta.messages.create(**self._request(question, context))
        self._check(response)
        return "".join(block.text for block in response.content if block.type == "text")

    def stream(self, question: str, context: Sequence[SearchResult]) -> Iterator[str]:
        """Yields the answer's text as Claude writes it; raises on refusal once it ends."""
        with self._client.beta.messages.stream(**self._request(question, context)) as stream:
            yield from stream.text_stream
            response = stream.get_final_message()
        self._check(response)

    def _request(self, question: str, context: Sequence[SearchResult]) -> dict[str, Any]:
        message: BetaMessageParam = {"role": "user", "content": build_prompt(question, context)}
        return {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": SYSTEM_PROMPT,
            "output_config": {"effort": self._effort},
            "betas": ["server-side-fallback-2026-07-01"],
            "fallbacks": "default",
            "messages": [message],
        }

    def _check(self, response: BetaMessage) -> None:
        logger.debug(
            "claude response",
            extra={
                "model": response.model,
                "stop_reason": response.stop_reason,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        )
        if response.stop_reason == "refusal":
            logger.warning("claude refused to answer", extra={"model": response.model})
            raise GenerationRefusedError("The model declined to answer this question.")


def build_prompt(question: str, context: Sequence[SearchResult]) -> str:
    passages = "\n\n".join(
        f"[{index}] (source: {result.chunk.citation})\n{result.chunk.text}"
        for index, result in enumerate(context, start=1)
    )
    return f"<context>\n{passages}\n</context>\n\nQuestion: {question}"
