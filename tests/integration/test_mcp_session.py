"""End-to-end MCP tests: one client session drives a real container over an on-disk index.

Only the answer generator is faked, so no test ever calls the Claude API.
"""

import asyncio
import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("mcp")

from mcp import Client, MCPError  # noqa: E402
from mcp.types import INVALID_PARAMS  # noqa: E402

from docsage.container import Container, Settings  # noqa: E402
from docsage.interfaces.mcp_server import build_server  # noqa: E402

CORPUS = Path(__file__).resolve().parents[1] / "fixtures" / "corpus"


class FakeGenerator:
    def __init__(self):
        self.calls = []

    def generate(self, question, context):
        self.calls.append((question, list(context)))
        return "Install it with pip [1]."


@pytest.fixture
def corpus(tmp_path):
    folder = tmp_path / "corpus"
    shutil.copytree(CORPUS, folder)
    return folder


@pytest.fixture
def generator():
    return FakeGenerator()


@pytest.fixture
def services(tmp_path, generator):
    return Container(Settings(index_path=tmp_path / "index.json"), generator)


def text_of(result):
    return "\n".join(block.text for block in result.content)


def documents_in(result):
    return json.loads(result.contents[0].text)["documents"]


def test_a_client_session_indexes_reads_searches_asks_and_removes(corpus, services, generator):
    async def session():
        async with Client(build_server(services)) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert tools.keys() == {
                "search_documents",
                "ask_documents",
                "index_path",
                "remove_path",
                "index_stats",
            }
            assert tools["remove_path"].annotations.destructive_hint is True
            assert tools["index_path"].annotations.destructive_hint is False

            indexed = await client.call_tool("index_path", {"path": str(corpus)})
            assert text_of(indexed).startswith("Indexed 3 documents into")

            listing = documents_in(await client.read_resource("docsage://documents"))
            by_name = {Path(item["source"]).name: item for item in listing}
            assert by_name.keys() == {"install.md", "retrieval.md", "faq.txt"}
            assert by_name["install.md"]["sections"] == [
                "Installation",
                "Installation > Optional extras",
                "Upgrading",
            ]

            chunk_id = by_name["retrieval.md"]["chunk_ids"][0]
            chunk = json.loads(
                (await client.read_resource(f"docsage://chunks/{chunk_id}")).contents[0].text
            )
            assert "BM25" in chunk["text"]

            found = text_of(await client.call_tool("search_documents", {"query": "BM25"}))
            assert found.splitlines()[2].startswith("[1] ")
            assert "retrieval.md, Retrieval" in found

            source = by_name["install.md"]["source"]
            prompt = await client.get_prompt("summarize_document", {"source": source})
            prompt_text = prompt.messages[0].content.text
            assert "[1] " in prompt_text and "Python 3.11" in prompt_text

            answer = text_of(
                await client.call_tool("ask_documents", {"question": "How do I install it?"})
            )
            assert answer.startswith("Install it with pip [1].")
            assert "Sources:" in answer

            stats = text_of(await client.call_tool("index_stats", {}))
            assert "Documents:  3" in stats

            removed = await client.call_tool("remove_path", {"path": str(corpus / "faq.txt")})
            assert text_of(removed).startswith("Removed 1 documents")
            remaining = documents_in(await client.read_resource("docsage://documents"))
            assert sorted(Path(item["source"]).name for item in remaining) == [
                "install.md",
                "retrieval.md",
            ]
            gone = await client.call_tool("search_documents", {"query": "offline"})
            assert "No indexed passages" in text_of(gone)

    asyncio.run(session())

    ((question, context),) = generator.calls
    assert question == "How do I install it?"
    assert any("pip" in result.chunk.text for result in context)


def test_errors_do_not_end_the_session(corpus, services):
    async def session():
        async with Client(build_server(services)) as client:
            missing = await client.call_tool("index_path", {"path": str(corpus / "nope")})
            assert missing.is_error
            empty = await client.call_tool("search_documents", {"query": "  "})
            assert empty.is_error

            with pytest.raises(MCPError) as unknown_prompt:
                await client.get_prompt("summarize_document", {"source": "nope.md"})
            assert unknown_prompt.value.code == INVALID_PARAMS

            indexed = await client.call_tool("index_path", {"path": str(corpus)})
            assert not indexed.is_error

    asyncio.run(session())


def test_a_new_server_on_the_same_index_sees_earlier_work(corpus, tmp_path):
    settings = Settings(index_path=tmp_path / "index.json")

    async def index_then_reconnect():
        async with Client(build_server(Container(settings))) as first:
            await first.call_tool("index_path", {"path": str(corpus)})
        async with Client(build_server(Container(settings))) as second:
            unchanged = await second.call_tool("index_path", {"path": str(corpus)})
            listing = await second.read_resource("docsage://documents")
            return text_of(unchanged), documents_in(listing)

    unchanged, listing = asyncio.run(index_then_reconnect())

    assert "Skipped 3 unchanged documents" in unchanged
    assert len(listing) == 3
