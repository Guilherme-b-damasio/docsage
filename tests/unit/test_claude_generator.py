import logging
from types import SimpleNamespace

import pytest

from docsage.domain.models import Chunk, SearchResult
from docsage.infrastructure.claude_generator import (
    ClaudeAnswerGenerator,
    GenerationRefusedError,
    build_content,
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
        self.kwargs = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self._response


class _FakeClient:
    def __init__(self, response):
        self.beta = SimpleNamespace(messages=_FakeMessages(response))


def _response(stop_reason: str, text: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        model="claude-opus-5-5",
        stop_reason=stop_reason,
        usage=SimpleNamespace(
            input_tokens=120,
            output_tokens=8,
            cache_creation_input_tokens=None,
            cache_read_input_tokens=900,
        ),
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


class _FakeStream:
    def __init__(self, pieces, response):
        self.text_stream = iter(pieces)
        self._response = response

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self._response


class _FakeStreamingMessages:
    def __init__(self, pieces, response):
        self._pieces = pieces
        self._response = response
        self.kwargs = None

    def stream(self, **kwargs):
        self.kwargs = kwargs
        return _FakeStream(self._pieces, self._response)


class _FakeStreamingClient:
    def __init__(self, pieces, response):
        self.beta = SimpleNamespace(messages=_FakeStreamingMessages(pieces, response))


def test_stream_yields_text_as_it_arrives():
    client = _FakeStreamingClient(["It ", "ranks ", "[1]."], _response("end_turn"))
    generator = ClaudeAnswerGenerator(client=client)

    assert list(generator.stream("how?", _context())) == ["It ", "ranks ", "[1]."]
    assert client.beta.messages.kwargs["output_config"] == {"effort": "medium"}
    assert client.beta.messages.kwargs["model"] == "claude-opus-5-5"


def test_stream_raises_on_refusal_after_the_text():
    generator = ClaudeAnswerGenerator(client=_FakeStreamingClient(["I "], _response("refusal")))

    with pytest.raises(GenerationRefusedError):
        list(generator.stream("how?", _context()))


def test_claude_generator_is_a_streaming_generator():
    from docsage.domain.ports import StreamingAnswerGenerator

    generator = ClaudeAnswerGenerator(client=_FakeClient(_response("end_turn")))

    assert isinstance(generator, StreamingAnswerGenerator)


def test_context_block_is_marked_for_prompt_caching_before_the_question():
    content = build_content("how?", _context())

    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert content[0]["text"].startswith("<context>\n[1] (source: a.md)")
    assert content[1] == {"type": "text", "text": "Question: how?"}


def test_generate_sends_the_cached_context_block():
    client = _FakeClient(_response("end_turn", "It ranks [1]."))

    ClaudeAnswerGenerator(client=client).generate("how?", _context())

    [message] = client.beta.messages.kwargs["messages"]
    assert "cache_control" in message["content"][0]


def test_cache_context_can_be_turned_off():
    client = _FakeClient(_response("end_turn", "It ranks [1]."))

    ClaudeAnswerGenerator(client=client, cache_context=False).generate("how?", _context())

    [message] = client.beta.messages.kwargs["messages"]
    assert all("cache_control" not in block for block in message["content"])


def test_generate_logs_cache_usage(caplog):
    caplog.set_level(logging.DEBUG, logger="docsage")
    generator = ClaudeAnswerGenerator(client=_FakeClient(_response("end_turn", "It ranks [1].")))

    generator.generate("how?", _context())

    record = next(r for r in caplog.records if r.getMessage() == "claude response")
    assert (record.cache_creation_input_tokens, record.cache_read_input_tokens) == (0, 900)
