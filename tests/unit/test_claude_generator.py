import logging
from types import SimpleNamespace

import pytest

from docsage.domain.models import Chunk, SearchResult, TokenUsage
from docsage.domain.ports import UsageReportingGenerator
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


def test_converse_sends_earlier_turns_before_the_question():
    from docsage.domain.models import ChatTurn

    client = _FakeStreamingClient(["In v2 ", "too [1]."], _response("end_turn"))
    history = [ChatTurn("what ranks?", "BM25 [1].")]

    pieces = list(ClaudeAnswerGenerator(client=client).converse("and in v2?", _context(), history))

    assert pieces == ["In v2 ", "too [1]."]
    messages = client.beta.messages.kwargs["messages"]
    assert messages[0] == {"role": "user", "content": "Question: what ranks?"}
    assert messages[1] == {"role": "assistant", "content": "BM25 [1]."}
    assert messages[2]["role"] == "user"
    assert messages[2]["content"][-1] == {"type": "text", "text": "Question: and in v2?"}
    assert "Earlier turns" in client.beta.messages.kwargs["system"]
    assert client.beta.messages.kwargs["output_config"] == {"effort": "medium"}


def test_converse_without_history_sends_one_message():
    client = _FakeStreamingClient(["ok"], _response("end_turn"))

    list(ClaudeAnswerGenerator(client=client).converse("how?", _context(), []))

    assert len(client.beta.messages.kwargs["messages"]) == 1


def test_converse_raises_on_refusal():
    generator = ClaudeAnswerGenerator(client=_FakeStreamingClient(["I "], _response("refusal")))

    with pytest.raises(GenerationRefusedError):
        list(generator.converse("how?", _context(), []))


def test_single_questions_keep_the_plain_system_prompt():
    from docsage.infrastructure.claude_generator import SYSTEM_PROMPT

    client = _FakeClient(_response("end_turn", "It ranks [1]."))

    ClaudeAnswerGenerator(client=client).generate("how?", _context())

    assert client.beta.messages.kwargs["system"] == SYSTEM_PROMPT


def test_default_system_prompt_answers_in_the_language_of_the_question():
    from docsage.infrastructure.claude_generator import SYSTEM_PROMPT, build_system_prompt

    assert build_system_prompt() == SYSTEM_PROMPT
    assert "Answer in the language of the question." in SYSTEM_PROMPT
    assert "short" not in SYSTEM_PROMPT


def test_style_fixes_the_answer_language_and_length():
    from docsage.domain.models import AnswerStyle
    from docsage.infrastructure.claude_generator import build_system_prompt

    prompt = build_system_prompt(AnswerStyle(language="Portuguese", length="short"))

    assert "Answer in Portuguese, whatever the language of the question." in prompt
    assert "language of the question." not in prompt.replace("whatever the language", "")
    assert "two or three sentences" in prompt


def test_long_answers_ask_for_detail_and_chat_adds_its_rules():
    from docsage.domain.models import AnswerStyle
    from docsage.infrastructure.claude_generator import build_system_prompt

    prompt = build_system_prompt(AnswerStyle(length="long"), chat=True)

    assert "thorough answer" in prompt
    assert prompt.endswith("context passages of the latest turn.")


def test_generator_sends_its_style_in_every_request():
    from docsage.domain.models import AnswerStyle

    client = _FakeClient(_response("end_turn", "Curto [1]."))
    style = AnswerStyle(language="Portuguese", length="short")

    ClaudeAnswerGenerator(client=client, style=style).generate("how?", _context())

    system = client.beta.messages.kwargs["system"]
    assert "Answer in Portuguese" in system
    assert "two or three sentences" in system


def test_converse_keeps_the_style():
    from docsage.domain.models import AnswerStyle

    client = _FakeStreamingClient(["ok"], _response("end_turn"))
    generator = ClaudeAnswerGenerator(client=client, style=AnswerStyle(language="English"))

    list(generator.converse("e agora?", _context(), []))

    system = client.beta.messages.kwargs["system"]
    assert "Answer in English" in system
    assert "Earlier turns" in system


def test_generator_reports_the_usage_of_its_last_answer():
    generator = ClaudeAnswerGenerator(client=_FakeClient(_response("end_turn", "It ranks [1].")))
    assert generator.last_usage is None

    generator.generate("how?", _context())

    assert generator.last_usage == TokenUsage(
        model="claude-opus-5-5",
        input_tokens=120,
        output_tokens=8,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=900,
    )
    assert generator.last_usage.total_input_tokens == 1020


def test_streamed_answers_report_their_usage_once_finished():
    generator = ClaudeAnswerGenerator(
        client=_FakeStreamingClient(["It ", "ranks."], _response("end_turn"))
    )

    pieces = generator.stream("how?", _context())
    assert generator.last_usage is None
    "".join(pieces)

    assert generator.last_usage is not None
    assert generator.last_usage.output_tokens == 8


def test_claude_generator_reports_usage():
    assert isinstance(ClaudeAnswerGenerator(client=_FakeClient(None)), UsageReportingGenerator)
