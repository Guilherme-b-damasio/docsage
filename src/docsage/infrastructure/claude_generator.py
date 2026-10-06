"""Answer generation backed by the Claude API."""

from __future__ import annotations

from collections.abc import Sequence

import anthropic

from docsage.domain.models import SearchResult

DEFAULT_MODEL = "claude-opus-5-5"

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
        effort: str = "medium",
        max_tokens: int = 16000,
    ) -> None:
        self._client = client or anthropic.Anthropic()
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens

    def generate(self, question: str, context: Sequence[SearchResult]) -> str:
        response = self._client.beta.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=SYSTEM_PROMPT,
            output_config={"effort": self._effort},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": build_prompt(question, context)}],
        )
        if response.stop_reason == "refusal":
            raise GenerationRefusedError("The model declined to answer this question.")
        return "".join(block.text for block in response.content if block.type == "text")


def build_prompt(question: str, context: Sequence[SearchResult]) -> str:
    passages = "\n\n".join(
        f"[{index}] (source: {result.chunk.source})\n{result.chunk.text}"
        for index, result in enumerate(context, start=1)
    )
    return f"<context>\n{passages}\n</context>\n\nQuestion: {question}"
