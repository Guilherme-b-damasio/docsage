"""Answer generation backed by the Claude API."""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from typing import Any, Literal

import anthropic
from anthropic.types.beta import BetaMessage, BetaMessageParam, BetaTextBlockParam

from docsage.domain.models import AnswerStyle, ChatTurn, SearchResult, TokenUsage

DEFAULT_MODEL = "claude-opus-5-5"

Effort = Literal["low", "medium", "high", "xhigh", "max"]

logger = logging.getLogger(__name__)

GROUNDING_PROMPT = (
    "You answer questions using only the numbered context passages provided. "
    "Cite passages inline as [1], [2], etc. If the context does not contain the "
    "answer, say so plainly instead of guessing."
)

CHAT_PROMPT = (
    "Earlier turns of the conversation come first: use them to understand follow-up "
    "questions, but ground every answer on the context passages of the latest turn."
)

LENGTH_PROMPTS = {
    "short": "Keep the answer short: two or three sentences at most.",
    "medium": "",
    "long": (
        "Give a thorough answer that covers every relevant detail in the passages, "
        "using lists or short sections where they help."
    ),
}


def build_system_prompt(style: AnswerStyle | None = None, chat: bool = False) -> str:
    """The instructions for one request: grounding, then language, length and chat rules."""
    style = style or AnswerStyle()
    language = (
        f"Answer in {style.language}, whatever the language of the question."
        if style.language
        else "Answer in the language of the question."
    )
    parts = [GROUNDING_PROMPT, language, LENGTH_PROMPTS[style.length]]
    if chat:
        parts.append(CHAT_PROMPT)
    return " ".join(part for part in parts if part)


SYSTEM_PROMPT = build_system_prompt()
"""The default instructions: answer in the question's language, at the model's own length."""


class GenerationRefusedError(RuntimeError):
    """Raised when the model declines to answer."""


class ClaudeAnswerGenerator:
    def __init__(
        self,
        client: anthropic.Anthropic | None = None,
        model: str = DEFAULT_MODEL,
        effort: Effort = "medium",
        max_tokens: int = 16000,
        cache_context: bool = True,
        style: AnswerStyle | None = None,
    ) -> None:
        """``cache_context`` marks the system prompt and the passages as a cacheable prefix, so
        a follow-up on the same passages reads them from Claude's prompt cache. ``style`` sets
        the language and length of every answer."""
        self._client = client or anthropic.Anthropic()
        self._model = model
        self._effort = effort
        self._max_tokens = max_tokens
        self._cache_context = cache_context
        self._style = style or AnswerStyle()
        self._last_usage: TokenUsage | None = None

    @property
    def last_usage(self) -> TokenUsage | None:
        """Tokens of the most recent finished answer, refusals included."""
        return self._last_usage

    def generate(self, question: str, context: Sequence[SearchResult]) -> str:
        response = self._client.beta.messages.create(**self._request(question, context))
        self._check(response)
        return "".join(block.text for block in response.content if block.type == "text")

    def stream(self, question: str, context: Sequence[SearchResult]) -> Iterator[str]:
        """Yields the answer's text as Claude writes it; raises on refusal once it ends."""
        return self._stream(self._request(question, context))

    def converse(
        self, question: str, context: Sequence[SearchResult], history: Sequence[ChatTurn]
    ) -> Iterator[str]:
        """Like ``stream``, with the earlier turns sent before the question as plain text."""
        return self._stream(self._request(question, context, history))

    def _stream(self, request: dict[str, Any]) -> Iterator[str]:
        with self._client.beta.messages.stream(**request) as stream:
            yield from stream.text_stream
            response = stream.get_final_message()
        self._check(response)

    def _request(
        self,
        question: str,
        context: Sequence[SearchResult],
        history: Sequence[ChatTurn] | None = None,
    ) -> dict[str, Any]:
        message: BetaMessageParam = {
            "role": "user",
            "content": build_content(question, context, self._cache_context),
        }
        return {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": build_system_prompt(self._style, chat=history is not None),
            "output_config": {"effort": self._effort},
            "betas": ["server-side-fallback-2026-07-01"],
            "fallbacks": "default",
            "messages": [*build_history(history or ()), message],
        }

    def _check(self, response: BetaMessage) -> None:
        usage = self._last_usage = usage_of(response)
        logger.debug(
            "claude response",
            extra={
                "model": usage.model,
                "stop_reason": response.stop_reason,
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "cache_creation_input_tokens": usage.cache_creation_input_tokens,
                "cache_read_input_tokens": usage.cache_read_input_tokens,
            },
        )
        if response.stop_reason == "refusal":
            logger.warning("claude refused to answer", extra={"model": response.model})
            raise GenerationRefusedError("The model declined to answer this question.")


def usage_of(response: BetaMessage) -> TokenUsage:
    """The token counts of a response; the cache fields are None when caching was not used."""
    return TokenUsage(
        model=response.model,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        cache_creation_input_tokens=response.usage.cache_creation_input_tokens or 0,
        cache_read_input_tokens=response.usage.cache_read_input_tokens or 0,
    )


def build_history(history: Sequence[ChatTurn]) -> list[BetaMessageParam]:
    """Earlier turns as alternating user and assistant messages. Only the questions and the
    answers are kept: the passages of old turns are left out to keep the request small."""
    messages: list[BetaMessageParam] = []
    for turn in history:
        messages.append({"role": "user", "content": f"Question: {turn.question}"})
        messages.append({"role": "assistant", "content": turn.answer})
    return messages


def build_context(context: Sequence[SearchResult]) -> str:
    """The numbered passages, rendered the same way for the same results so they can be cached."""
    passages = "\n\n".join(
        f"[{index}] (source: {result.chunk.citation})\n{result.chunk.text}"
        for index, result in enumerate(context, start=1)
    )
    return f"<context>\n{passages}\n</context>"


def build_content(
    question: str, context: Sequence[SearchResult], cache_context: bool = True
) -> list[BetaTextBlockParam]:
    """The passages first, then the question in its own block, so a cache breakpoint on the
    passages leaves the question (the part that changes) after the cached prefix."""
    passages: BetaTextBlockParam = {"type": "text", "text": build_context(context)}
    if cache_context:
        passages["cache_control"] = {"type": "ephemeral"}
    return [passages, {"type": "text", "text": f"Question: {question}"}]


def build_prompt(question: str, context: Sequence[SearchResult]) -> str:
    """The whole user turn as plain text, as Claude reads it."""
    return "\n\n".join(block["text"] for block in build_content(question, context))
