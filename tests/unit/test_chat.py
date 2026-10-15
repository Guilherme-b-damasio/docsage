import pytest

from docsage.application.services import NO_CONTEXT_ANSWER, ChatService
from docsage.domain.models import ChatTurn, Chunk, TokenUsage
from docsage.infrastructure.bm25 import BM25Retriever


class FakeConversationalGenerator:
    def __init__(self):
        self.calls = []

    def converse(self, question, context, history):
        self.calls.append((question, list(context), list(history)))
        yield f"answer {len(self.calls)} "
        yield f"after {len(history)} turns"


def _retriever() -> BM25Retriever:
    retriever = BM25Retriever()
    retriever.add(
        [
            Chunk(id="a", source="a.md", text="alpha release notes", position=0),
            Chunk(id="b", source="b.md", text="beta install guide", position=0),
        ]
    )
    return retriever


def test_each_question_sees_the_earlier_turns():
    generator = FakeConversationalGenerator()
    chat = ChatService(_retriever(), generator)

    first = chat.ask("alpha")
    second = chat.ask("beta")

    assert first.text == "answer 1 after 0 turns"
    assert second.text == "answer 2 after 1 turns"
    assert generator.calls[1][2] == [ChatTurn("alpha", "answer 1 after 0 turns")]
    assert chat.history == (
        ChatTurn("alpha", "answer 1 after 0 turns"),
        ChatTurn("beta", "answer 2 after 1 turns"),
    )


def test_every_question_retrieves_its_own_passages():
    generator = FakeConversationalGenerator()
    chat = ChatService(_retriever(), generator)

    chat.ask("alpha")
    answer = chat.ask("beta")

    assert [result.chunk.id for result in answer.sources] == ["b"]
    assert [result.chunk.id for result in generator.calls[1][1]] == ["b"]


def test_pieces_reach_the_callback_as_they_are_written():
    pieces = []

    ChatService(_retriever(), FakeConversationalGenerator()).ask("alpha", on_text=pieces.append)

    assert pieces == ["answer 1 ", "after 0 turns"]


def test_only_the_most_recent_turns_are_sent():
    generator = FakeConversationalGenerator()
    chat = ChatService(_retriever(), generator, max_turns=2)

    for _ in range(4):
        chat.ask("alpha")

    assert [turn.answer for turn in generator.calls[3][2]] == [
        "answer 2 after 1 turns",
        "answer 3 after 2 turns",
    ]
    assert len(chat.history) == 4


def test_zero_max_turns_sends_no_history():
    generator = FakeConversationalGenerator()
    chat = ChatService(_retriever(), generator, max_turns=0)

    chat.ask("alpha")
    chat.ask("alpha")

    assert generator.calls[1][2] == []


def test_negative_max_turns_is_rejected():
    with pytest.raises(ValueError):
        ChatService(_retriever(), FakeConversationalGenerator(), max_turns=-1)


def test_reset_starts_a_new_conversation():
    generator = FakeConversationalGenerator()
    chat = ChatService(_retriever(), generator)
    chat.ask("alpha")

    chat.reset()
    chat.ask("beta")

    assert chat.history == (ChatTurn("beta", "answer 2 after 0 turns"),)
    assert generator.calls[1][2] == []


def test_question_without_context_is_answered_without_the_generator_and_not_remembered():
    generator = FakeConversationalGenerator()
    chat = ChatService(_retriever(), generator)
    pieces = []

    answer = chat.ask("nothing matches", on_text=pieces.append)

    assert answer.text == NO_CONTEXT_ANSWER
    assert pieces == [NO_CONTEXT_ANSWER]
    assert generator.calls == []
    assert chat.history == ()


class UsageReportingConversationalGenerator(FakeConversationalGenerator):
    def __init__(self):
        super().__init__()
        self.last_usage = None

    def converse(self, question, context, history):
        yield from super().converse(question, context, history)
        self.last_usage = TokenUsage(model="m", input_tokens=len(self.calls), output_tokens=5)


class PerTokenEstimator:
    def estimate(self, usage):
        return usage.total_input_tokens / 100


def test_each_chat_turn_reports_its_own_usage_and_cost():
    chat = ChatService(
        _retriever(), UsageReportingConversationalGenerator(), cost_estimator=PerTokenEstimator()
    )

    first = chat.ask("alpha")
    second = chat.ask("and beta?")

    assert (first.usage.input_tokens, first.cost_usd) == (1, 0.01)
    assert (second.usage.input_tokens, second.cost_usd) == (2, 0.02)
