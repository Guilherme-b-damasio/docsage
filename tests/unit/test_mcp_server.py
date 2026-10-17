import asyncio
import json

import pytest

pytest.importorskip("mcp")

from mcp import Client, MCPError  # noqa: E402
from mcp.types import INVALID_PARAMS  # noqa: E402

from docsage.application.services import (  # noqa: E402
    AnswerReportService,
    CatalogService,
    DashboardService,
    QuestionAnsweringService,
    RelationService,
    SearchService,
    StatsService,
)
from docsage.container import Container, Settings  # noqa: E402
from docsage.domain.models import Chunk, TokenUsage  # noqa: E402
from docsage.infrastructure.bm25 import BM25Retriever  # noqa: E402
from docsage.infrastructure.highlighting import TermHighlighter  # noqa: E402
from docsage.infrastructure.html_dashboard import HtmlDashboardRenderer  # noqa: E402
from docsage.infrastructure.html_report import HtmlAnswerRenderer  # noqa: E402
from docsage.infrastructure.mcp_app_view import APP_MIME_TYPE, HTML_META_KEY  # noqa: E402
from docsage.infrastructure.text_dashboard import TextDashboardRenderer  # noqa: E402
from docsage.infrastructure.tokenizer import multilingual_tokenizer  # noqa: E402
from docsage.infrastructure.web_loader import FetchedPage, WebPageLoader  # noqa: E402
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
        self.highlighter = TermHighlighter(multilingual_tokenizer())

    def search_service(self):
        return SearchService(self.retriever, self.highlighter)

    def question_answering_service(self):
        return QuestionAnsweringService(self.retriever, self.generator, self.highlighter)

    def answer_report_service(self, report_format="html"):
        assert report_format == "html"
        return AnswerReportService(self.question_answering_service(), HtmlAnswerRenderer())

    def stats_service(self):
        return StatsService(self.retriever, multilingual_tokenizer(), self)

    def catalog_service(self):
        return CatalogService(self.retriever)

    def dashboard_service(self, dashboard_format="html"):
        renderers = {"html": HtmlDashboardRenderer, "text": TextDashboardRenderer}
        renderer = renderers[dashboard_format]()
        relations = RelationService(self.retriever, multilingual_tokenizer())
        return DashboardService(self.stats_service(), self.retriever, renderer, relations)

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
    assert "[1] b.pdf, p. 3 (score " in text
    assert "; matched: capital, portugal)" in text
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

    assert "docsage://documents" in [str(item.uri) for item in resources.resources]
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


def test_every_tool_publishes_an_output_schema():
    async def run():
        async with Client(build_server(FakeServices())) as client:
            return await client.list_tools()

    schemas = {tool.name: tool.output_schema for tool in asyncio.run(run()).tools}

    assert all(schema and schema["type"] == "object" for schema in schemas.values())
    assert schemas["search_documents"]["required"] == ["query", "results"]
    assert set(schemas["index_stats"]["properties"]) == {
        "documents",
        "chunks",
        "terms",
        "vocabulary",
        "top_terms",
        "index_bytes",
    }


def test_search_documents_returns_structured_results_with_full_text():
    long_text = "alpha " * 200
    services = FakeServices([Chunk(id="l#0", source="long.md", text=long_text, position=0)])

    result = call(services, "search_documents", {"query": "alpha"})

    assert text_of(result).endswith("...")
    (ranked,) = result.structured_content["results"]
    assert result.structured_content["query"] == "alpha"
    assert ranked["rank"] == 1
    assert ranked["chunk"]["text"] == long_text
    assert ranked["chunk"]["citation"] == "long.md"


def test_ask_documents_returns_structured_answer():
    result = call(FakeServices(CHUNKS), "ask_documents", {"question": "France?", "top_k": 1})

    payload = result.structured_content
    assert payload["question"] == "France?"
    assert payload["answer"] == "Paris is the capital [1]."
    assert [source["chunk"]["id"] for source in payload["sources"]] == ["a#0"]


def test_index_stats_returns_structured_top_terms():
    payload = call(FakeServices(CHUNKS), "index_stats", {"top": 1}).structured_content

    assert payload["documents"] == 2
    assert payload["index_bytes"] == 2048
    assert payload["top_terms"] == [{"term": "capital", "count": 2}]


def test_failed_tools_carry_no_structured_content():
    result = call(FakeServices(), "index_stats", {"top": -1})

    assert result.is_error
    assert result.structured_content is None


def test_index_and_remove_return_structured_reports(tmp_path):
    (tmp_path / "a.md").write_text("alpha notes", encoding="utf-8")
    (tmp_path / "image.png").write_bytes(b"PNG-bytes")
    services = Container(Settings(index_path=tmp_path / "index.json"))

    indexed = call(services, "index_path", {"path": str(tmp_path)}).structured_content
    assert indexed["documents"] == 1
    assert indexed["unchanged"] == 0
    assert [path.endswith("image.png") for path in indexed["skipped"]] == [True]

    target = str(tmp_path / "a.md")
    removed = call(services, "remove_path", {"path": target}).structured_content
    assert removed["path"] == target
    assert removed["chunks"] == 1
    assert len(removed["documents"]) == 1


def test_search_documents_returns_highlight_offsets():
    result = call(FakeServices(CHUNKS), "search_documents", {"query": "Portugal capital"})

    top = result.structured_content["results"][0]
    assert top["matched_terms"] == ["capital", "portugal"]
    text = top["chunk"]["text"]
    assert [text[item["start"] : item["end"]] for item in top["highlights"]] == [
        "capital",
        "Portugal",
    ]


def test_search_documents_returns_the_score_breakdown():
    result = call(FakeServices(CHUNKS), "search_documents", {"query": "Portugal capital"})

    top = result.structured_content["results"][0]
    assert {item["term"] for item in top["contributions"]} == {"capital", "portugal"}
    assert sum(item["score"] for item in top["contributions"]) == pytest.approx(
        top["score"], abs=1e-3
    )


def test_index_dashboard_returns_text_numbers_and_the_html_page_for_its_view():
    result = call(FakeServices(CHUNKS), "index_dashboard", {"top": 3})

    assert not result.is_error
    assert "Documents" in text_of(result) and "<html" not in text_of(result)
    assert result.structured_content["documents"] == 2
    assert result.structured_content["documents_by_type"] == [
        {"type": "md", "documents": 1},
        {"type": "pdf", "documents": 1},
    ]
    assert sum(item["chunks"] for item in result.structured_content["chunk_lengths"]) == 2
    assert len(result.structured_content["top_terms"]) == 3
    assert result.structured_content["relations"] == [
        {"first": "a.md", "second": "b.pdf", "shared_terms": ["capital"]}
    ]
    assert result.structured_content["chunk_map"] == []
    assert result.meta[HTML_META_KEY].startswith("<!doctype html>")
    assert "<svg" in result.meta[HTML_META_KEY]


def test_index_dashboard_rejects_negative_top():
    result = call(FakeServices(CHUNKS), "index_dashboard", {"top": -1})

    assert result.is_error


def test_tools_without_a_view_carry_no_html():
    result = call(FakeServices(CHUNKS), "search_documents", {"query": "capital"})

    assert not (result.meta or {}).get(HTML_META_KEY)


def test_index_dashboard_links_its_mcp_apps_view():
    async def run():
        async with Client(build_server(FakeServices())) as client:
            tools = await client.list_tools()
            resources = await client.list_resources()
            return tools, resources

    tools, resources = asyncio.run(run())
    tool = next(item for item in tools.tools if item.name == "index_dashboard")
    view_uri = tool.meta["ui"]["resourceUri"]
    view = next(item for item in resources.resources if str(item.uri) == view_uri)

    assert view_uri.startswith("ui://")
    assert view.mime_type == APP_MIME_TYPE
    assert view.meta == {"ui": {"prefersBorder": True}}


def test_dashboard_view_is_the_mcp_apps_shell():
    result = read(FakeServices(), "ui://docsage/dashboard")
    content = result.contents[0]

    assert content.mime_type == APP_MIME_TYPE
    assert "ui/initialize" in content.text and HTML_META_KEY in content.text


def test_ask_documents_returns_the_html_report_for_its_view():
    result = call(FakeServices(CHUNKS), "ask_documents", {"question": "capital of France?"})

    html = result.meta[HTML_META_KEY]
    assert html.startswith("<!doctype html>")
    assert "capital of France?" in html and "<mark" in html
    assert "<mark" not in text_of(result)


def test_ask_documents_links_the_answer_report_view():
    async def run():
        async with Client(build_server(FakeServices())) as client:
            tools = await client.list_tools()
            view = await client.read_resource("ui://docsage/answer-report")
            return tools, view

    tools, view = asyncio.run(run())
    tool = next(item for item in tools.tools if item.name == "ask_documents")

    assert tool.meta == {"ui": {"resourceUri": "ui://docsage/answer-report"}}
    assert view.contents[0].mime_type == APP_MIME_TYPE


def test_ask_documents_reports_usage_in_text_and_structured_output():
    services = FakeServices(CHUNKS)
    usage = TokenUsage(model="claude-opus-5-5", input_tokens=1000, output_tokens=500)
    services.generator.last_usage = usage

    result = call(services, "ask_documents", {"question": "capital of France?", "top_k": 1})

    assert text_of(result).endswith(
        "Usage: claude-opus-5-5: 1,000 input tokens, 500 output tokens"
    )
    assert result.structured_content["usage"]["input_tokens"] == 1000
    assert result.structured_content["cost_usd"] is None


def _web_container(tmp_path, pages):
    def fetch(url):
        if url not in pages:
            raise OSError("connection refused")
        return FetchedPage(url, "text/html", "utf-8", pages[url].encode())

    return Container(
        Settings(index_path=tmp_path / "index.json"), url_loader=WebPageLoader(fetch)
    )


def test_index_url_and_remove_url_against_a_real_container(tmp_path):
    services = _web_container(
        tmp_path, {"https://x.io/docs/a": "<nav>Menu</nav><main><p>gamma rays</p></main>"}
    )

    indexed = call(services, "index_url", {"url": "https://x.io/docs/a"})
    assert text_of(indexed).startswith("Indexed 1 documents into 1 chunks.")
    assert indexed.structured_content["failed"] == []
    assert "https://x.io/docs/a" in text_of(
        call(services, "search_documents", {"query": "gamma"})
    )

    removed = text_of(call(services, "remove_url", {"url": "https://x.io/docs"}))
    assert removed.startswith("Removed 1 documents (1 chunks):")


def test_index_url_reports_unreachable_pages_as_errors(tmp_path):
    result = call(_web_container(tmp_path, {}), "index_url", {"url": "https://x.io/down"})

    assert result.is_error
    assert "connection refused" in text_of(result)


def test_url_tools_reject_addresses_that_are_not_http(tmp_path):
    services = _web_container(tmp_path, {})

    for tool in ("index_url", "remove_url"):
        result = call(services, tool, {"url": "file:///etc/passwd"})
        assert result.is_error
        assert "not an http(s) URL" in text_of(result)


def test_index_url_is_marked_open_world():
    async def run():
        async with Client(build_server(FakeServices())) as client:
            return await client.list_tools()

    tools = {tool.name: tool for tool in asyncio.run(run()).tools}

    assert tools["index_url"].annotations.open_world_hint is True
    assert tools["remove_url"].annotations.destructive_hint is True
