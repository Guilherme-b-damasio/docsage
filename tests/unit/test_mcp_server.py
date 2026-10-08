import asyncio

import pytest

pytest.importorskip("mcp")

from mcp import Client  # noqa: E402

from docsage.application.services import QuestionAnsweringService, SearchService  # noqa: E402
from docsage.domain.models import Chunk  # noqa: E402
from docsage.infrastructure.bm25 import BM25Retriever  # noqa: E402
from docsage.interfaces.mcp_server import PREVIEW_CHARACTERS, build_server  # noqa: E402


class FakeGenerator:
    def __init__(self):
        self.calls = []

    def generate(self, question, context):
        self.calls.append((question, list(context)))
        return "Paris is the capital [1]."


class FakeServices:
    def __init__(self, chunks=()):
        self.retriever = BM25Retriever()
        self.retriever.add(chunks)
        self.generator = FakeGenerator()

    def search_service(self):
        return SearchService(self.retriever)

    def question_answering_service(self):
        return QuestionAnsweringService(self.retriever, self.generator)


CHUNKS = [
    Chunk(id="a#0", source="a.md", text="The capital of France is Paris.", position=0),
    Chunk(
        id="b#0",
        source="b.pdf",
        text="Lisbon is the capital of Portugal.",
        position=0,
        first_page=3,
        last_page=3,
    ),
]


def call(services, tool, arguments):
    async def run():
        async with Client(build_server(services)) as client:
            return await client.call_tool(tool, arguments)

    return asyncio.run(run())


def text_of(result):
    return "\n".join(block.text for block in result.content)


def test_lists_search_and_ask_tools():
    async def run():
        async with Client(build_server(FakeServices())) as client:
            return await client.list_tools()

    tools = {tool.name: tool for tool in asyncio.run(run()).tools}

    assert {"search_documents", "ask_documents"} <= tools.keys()
    assert tools["search_documents"].annotations.read_only_hint is True
    assert tools["search_documents"].input_schema["required"] == ["query"]


def test_search_documents_returns_ranked_citations():
    result = call(FakeServices(CHUNKS), "search_documents", {"query": "Portugal capital"})

    assert not result.is_error
    text = text_of(result)
    assert text.startswith('2 passages for "Portugal capital":')
    assert "[1] b.pdf, p. 3" in text
    assert "Lisbon is the capital of Portugal." in text


def test_search_documents_without_matches():
    result = call(FakeServices(CHUNKS), "search_documents", {"query": "kangaroo"})

    assert text_of(result) == 'No indexed passages match "kangaroo".'


def test_search_documents_rejects_bad_arguments():
    services = FakeServices(CHUNKS)

    assert call(services, "search_documents", {"query": "  "}).is_error
    result = call(services, "search_documents", {"query": "paris", "top_k": 0})
    assert result.is_error
    assert "top_k must be at least 1" in text_of(result)


def test_ask_documents_answers_with_sources():
    services = FakeServices(CHUNKS)

    result = call(services, "ask_documents", {"question": "capital of France?", "top_k": 1})

    assert text_of(result) == "Paris is the capital [1].\n\nSources:\n[1] a.md"
    question, context = services.generator.calls[0]
    assert question == "capital of France?"
    assert [item.chunk.id for item in context] == ["a#0"]


def test_ask_documents_on_empty_index_skips_the_generator():
    services = FakeServices()

    result = call(services, "ask_documents", {"question": "anything?"})

    assert text_of(result) == "No relevant context found in the index."
    assert services.generator.calls == []


def test_search_documents_truncates_long_passages():
    long_text = "alpha " * 200
    services = FakeServices([Chunk(id="l#0", source="long.md", text=long_text, position=0)])

    text = text_of(call(services, "search_documents", {"query": "alpha"}))

    assert text.endswith("...")
    assert len(text.splitlines()[-1]) <= PREVIEW_CHARACTERS + 3
