import logging
from types import SimpleNamespace

import pytest

from docsage.domain.models import Chunk, SearchResult
from docsage.infrastructure.claude_generator import (
    ClaudeAnswerGenerator,
    GenerationRefusedError,
    build_prompt,
)


def test_prompt_cites_the_pages_of_each_passage():
    chunk = Chunk(id="p", source="guide.pdf", text="BM25 ranks", position=0, first_page=4)

    prompt = build_prompt("how?", [SearchResult(chunk, 1.0)])

    assert "[1] (source: guide.pdf, p. 4)\nBM25 ranks" in prompt
    assert prompt.endswith("Question: how?")


class _FakeMessages:
    def __init__(self, response):
        self._response = response

    def create(self, **kwargs):
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.beta = SimpleNamespace(messages=_FakeMessages(response))


def _response(stop_reason: str, text: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        model="claude-opus-5-5",
        stop_reason=stop_reason,
        usage=SimpleNamespace(input_tokens=120, output_tokens=8),
        content=[SimpleNamespace(type="text", text=text)] if text else [],
    )


def _context() -> list[SearchResult]:
    return [SearchResult(Chunk(id="c", source="a.md", text="BM25", position=0), 1.0)]


def test_generate_logs_token_usage(caplog):
    caplog.set_level(logging.DEBUG, logger="docsage")
    generator = ClaudeAnswerGenerator(client=_FakeClient(_response("end_turn", "It ranks [1].")))

    assert generator.generate("how?", _context()) == "It ranks [1]."

    record = next(r for r in caplog.records if r.getMessage() == "claude response")
    assert (record.input_tokens, record.output_tokens) == (120, 8)
    assert record.stop_reason == "end_turn"


def test_generate_raises_and_warns_on_refusal(caplog):
    generator = ClaudeAnswerGenerator(client=_FakeClient(_response("refusal")))

    with pytest.raises(GenerationRefusedError):
        generator.generate("how?", _context())

    assert any(r.levelno == logging.WARNING for r in caplog.records)
