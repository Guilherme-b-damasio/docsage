import asyncio
import json

import pytest

pytest.importorskip("mcp")

from mcp import Client, MCPError  # noqa: E402
from mcp.types import INVALID_PARAMS  # noqa: E402

from docsage.application.services import (  # noqa: E402
    CatalogService,
    QuestionAnsweringService,
    SearchService,
    StatsService,
)
from docsage.container import Container, Settings  # noqa: E402
from docsage.domain.models import Chunk  # noqa: E402
from docsage.infrastructure.bm25 import BM25Retriever  # noqa: E402
from docsage.infrastructure.tokenizer import multilingual_tokenizer  # noqa: E402
from docsage.interfaces.mcp_server import (  # noqa: E402
    PREVIEW_CHARACTERS,
    build_server,
    format_passages,
)


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

    def stats_service(self):
        return StatsService(self.retriever, multilingual_tokenizer(), self)

    def catalog_service(self):
        return CatalogService(self.retriever)

    def size_bytes(self):
        return 2048


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


def read(services, uri):
    async def run():
        async with Client(build_server(services)) as client:
            return await client.read_resource(uri)

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


def test_index_stats_summarizes_the_index():
    text = text_of(call(FakeServices(CHUNKS), "index_stats", {"top": 2}))

    assert "Documents:  2" in text
    assert "Chunks:     2" in text
    assert "Index size: 2.0 KB" in text
    assert text.splitlines()[-1] == "Top terms: capital (2), france (1)"


def test_index_stats_rejects_negative_top():
    assert call(FakeServices(), "index_stats", {"top": -1}).is_error


def test_index_search_and_remove_against_a_real_container(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("alpha notes", encoding="utf-8")
    (docs / "b.md").write_text("beta notes", encoding="utf-8")
    (docs / "image.png").write_bytes(b"PNG-bytes")
    services = Container(Settings(index_path=tmp_path / "index.json"))

    indexed = text_of(call(services, "index_path", {"path": str(docs)}))
    assert indexed.startswith("Indexed 2 documents into 2 chunks.")
    assert "Skipped 1 unsupported files:" in indexed

    again = text_of(call(services, "index_path", {"path": str(docs)}))
    assert "Skipped 2 unchanged documents" in again
    forced = call(services, "index_path", {"path": str(docs), "force": True})
    assert text_of(forced).startswith("Indexed 2 documents")

    assert "alpha notes" in text_of(call(services, "search_documents", {"query": "alpha"}))

    removed = text_of(call(services, "remove_path", {"path": str(docs / "a.md")}))
    assert removed.startswith("Removed 1 documents (1 chunks):")
    assert "No indexed passages" in text_of(
        call(services, "search_documents", {"query": "alpha"})
    )
    missing = text_of(call(services, "remove_path", {"path": str(docs / "a.md")}))
    assert missing == f"Nothing indexed under {docs / 'a.md'}."


def test_index_path_rejects_missing_paths(tmp_path):
    services = Container(Settings(index_path=tmp_path / "index.json"))

    result = call(services, "index_path", {"path": str(tmp_path / "nope")})

    assert result.is_error
    assert "does not exist" in text_of(result)


def test_lists_documents_resource_and_chunk_template():
    async def run():
        async with Client(build_server(FakeServices())) as client:
            return await client.list_resources(), await client.list_resource_templates()

    resources, templates = asyncio.run(run())

    assert [str(item.uri) for item in resources.resources] == ["docsage://documents"]
    assert [item.uri_template for item in templates.resource_templates] == [
        "docsage://chunks/{chunk_id}"
    ]


def test_documents_resource_lists_sources_with_chunk_ids():
    result = read(FakeServices(CHUNKS), "docsage://documents")

    content = result.contents[0]
    assert content.mime_type == "application/json"
    documents = json.loads(content.text)["documents"]
    assert documents == [
        {"source": "a.md", "chunks": 1, "pages": None, "sections": [], "chunk_ids": ["a#0"]},
        {"source": "b.pdf", "chunks": 1, "pages": 3, "sections": [], "chunk_ids": ["b#0"]},
    ]


def test_documents_resource_of_an_empty_index():
    result = read(FakeServices(), "docsage://documents")

    assert json.loads(result.contents[0].text) == {"documents": []}


def test_chunk_resource_returns_text_and_citation():
    chunk = Chunk(id="abc-0", source="b.pdf", text="Lisbon.", position=0, first_page=3)

    result = read(FakeServices([chunk]), "docsage://chunks/abc-0")

    payload = json.loads(result.contents[0].text)
    assert payload["text"] == "Lisbon."
    assert payload["citation"] == "b.pdf, p. 3"


def test_chunk_resource_rejects_unknown_ids():
    async def run():
        async with Client(build_server(FakeServices(CHUNKS))) as client:
            with pytest.raises(MCPError, match="No indexed chunk with id nope") as error:
                await client.read_resource("docsage://chunks/nope")
            return error.value

    assert asyncio.run(run()).code == INVALID_PARAMS


def test_resources_against_a_real_container(tmp_path):
    (tmp_path / "notes.md").write_text("# Setup\n\nInstall with pip.", encoding="utf-8")
    services = Container(Settings(index_path=tmp_path / "index.json"))
    call(services, "index_path", {"path": str(tmp_path / "notes.md")})

    documents = json.loads(read(services, "docsage://documents").contents[0].text)["documents"]
    (document,) = documents
    assert document["sections"] == ["Setup"]

    (chunk_id,) = document["chunk_ids"]
    chunk = json.loads(read(services, f"docsage://chunks/{chunk_id}").contents[0].text)
    assert "Install with pip." in chunk["text"]
    assert chunk["citation"].endswith("notes.md, Setup")


def get_prompt(services, name, arguments):
    async def run():
        async with Client(build_server(services)) as client:
            return await client.get_prompt(name, arguments)

    return asyncio.run(run())


SECTIONED = [
    Chunk(id="n-1", source="notes.md", text="Use pip.", position=1, section="Install"),
    Chunk(id="n-0", source="notes.md", text="docsage indexes files.", position=0, section="Intro"),
    Chunk(id="o-0", source="old.md", text="Use setup.py.", position=0, section="Install"),
]


def test_lists_prompts_with_their_arguments():
    async def run():
        async with Client(build_server(FakeServices())) as client:
            return await client.list_prompts()

    prompts = {prompt.name: prompt for prompt in asyncio.run(run()).prompts}

    assert [arg.name for arg in prompts["summarize_document"].arguments] == ["source"]
    assert [arg.name for arg in prompts["compare_documents"].arguments] == ["first", "second"]
    assert all(arg.required for prompt in prompts.values() for arg in prompt.arguments)


def test_summarize_document_embeds_numbered_passages_in_order():
    result = get_prompt(FakeServices(SECTIONED), "summarize_document", {"source": "notes.md"})

    (message,) = result.messages
    assert message.role == "user"
    text = message.content.text
    assert text.startswith("Summarize the document notes.md")
    assert text.endswith(
        "[1] notes.md, Intro\ndocsage indexes files.\n\n[2] notes.md, Install\nUse pip."
    )
    assert "old.md" not in text


def test_compare_documents_labels_passages_per_document():
    result = get_prompt(
        FakeServices(SECTIONED), "compare_documents", {"first": "notes.md", "second": "old.md"}
    )

    text = result.messages[0].content.text
    assert "Document A: notes.md\n\n[A1] notes.md, Intro" in text
    assert "[A2] notes.md, Install\nUse pip." in text
    assert text.endswith("Document B: old.md\n\n[B1] old.md, Install\nUse setup.py.")


def test_prompts_reject_documents_that_are_not_indexed():
    async def run():
        async with Client(build_server(FakeServices(SECTIONED))) as client:
            with pytest.raises(MCPError, match="missing.md is not indexed") as error:
                await client.get_prompt(
                    "compare_documents", {"first": "notes.md", "second": "missing.md"}
                )
            return error.value

    assert asyncio.run(run()).code == INVALID_PARAMS


def test_format_passages_stops_at_the_budget():
    chunks = [
        Chunk(id=f"c-{n}", source="big.md", text="x" * 50, position=n) for n in range(5)
    ]

    text = format_passages(chunks, budget=130)

    assert text.count("big.md\n") == 2
    assert text.endswith("[3 more passages omitted to fit the prompt]")


def test_format_passages_keeps_one_passage_even_over_budget():
    chunk = Chunk(id="c-0", source="big.md", text="x" * 500, position=0)

    assert format_passages([chunk], budget=10) == f"[1] big.md\n{'x' * 500}"
