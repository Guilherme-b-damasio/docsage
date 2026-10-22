"""MCP server. Thin layer like the CLI: validate arguments, call a use case, format output.

Every tool returns readable text for the model plus structured content that matches
its published output schema (``docsage.interfaces.mcp_schemas``) for applications.
Tools with visual output also link an MCP Apps view (a ``ui://`` resource): hosts that
support MCP Apps show the rendered HTML page, the others show the text.

With ``watch`` folders the server also keeps the index in sync with them while it runs
and tells listening clients (``subscriptions/listen``) that ``docsage://documents``
changed.

Requires the optional ``mcp`` extra (``pip install "docsage[mcp]"``).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import AbstractAsyncContextManager, AbstractContextManager, asynccontextmanager
from pathlib import Path
from typing import Annotated, Any, Protocol

from anyio.from_thread import BlockingPortal
from mcp import MCPError
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
from mcp.server.subscriptions import InMemorySubscriptionBus, SubscriptionBus
from mcp.shared.subscriptions import ResourcesListChanged, ResourceUpdated
from mcp.types import INVALID_PARAMS, CallToolResult, TextContent, ToolAnnotations

from docsage import __version__
from docsage.application.services import (
    AnswerReportService,
    CatalogService,
    DashboardService,
    IndexingReport,
    IndexingService,
    LiveWatchService,
    QuestionAnsweringService,
    RemovalReport,
    RemovalService,
    SearchReportService,
    StatsReportService,
    StatsService,
    WatchUpdate,
)
from docsage.domain.models import Answer, Chunk, IndexStats, SearchResult, is_url
from docsage.infrastructure.mcp_app_view import APP_MIME_TYPE, HTML_META_KEY, FollowUp, app_view
from docsage.infrastructure.units import human_size, usage_summary
from docsage.interfaces.mcp_schemas import (
    AnswerOutput,
    DashboardOutput,
    IndexingOutput,
    RemovalOutput,
    SearchOutput,
    StatsOutput,
)
from docsage.interfaces.paths import expand_paths
from docsage.interfaces.serializers import (
    answer_to_dict,
    chunk_to_dict,
    document_summary_to_dict,
    dumps,
    indexing_report_to_dict,
    overview_to_dict,
    removal_report_to_dict,
    search_results_to_dict,
    stats_to_dict,
)

logger = logging.getLogger(__name__)

SERVER_NAME = "docsage"
DOCUMENTS_URI = "docsage://documents"
CHUNK_URI_TEMPLATE = "docsage://chunks/{chunk_id}"
DASHBOARD_VIEW_URI = "ui://docsage/dashboard"
ANSWER_VIEW_URI = "ui://docsage/answer-report"
SEARCH_VIEW_URI = "ui://docsage/search-results"
STATS_VIEW_URI = "ui://docsage/index-stats"
ASK_FOLLOW_UP = FollowUp("ask_documents", "question", "Ask a follow-up question", "Ask")
"""Lets the user ask another question from the answer report view."""
INSTRUCTIONS = (
    "Search and ask questions about the user's locally indexed documents. "
    "Use search_documents to find passages and ask_documents for a cited answer. "
    "index_path adds files or folders, remove_path drops them, index_url and remove_url "
    "do the same for web pages, index_stats summarizes "
    "and index_dashboard charts the index. "
    f"Read {DOCUMENTS_URI} to list indexed documents and their chunk ids, and "
    f"{CHUNK_URI_TEMPLATE} for the full text of one chunk. The summarize_document and "
    "compare_documents prompts embed whole documents as citable passages."
)
MAX_TOP_K = 50
MAX_TOP_TERMS = 100
PREVIEW_CHARACTERS = 400
PROMPT_CHARACTERS = 60_000
"""Budget for document text embedded in a prompt, split evenly between compared documents."""


class ServiceProvider(Protocol):
    """Builds the use cases the server calls; ``docsage.container.Container`` is one."""

    def search_report_service(self) -> SearchReportService: ...

    def question_answering_service(self) -> QuestionAnsweringService: ...

    def answer_report_service(self, report_format: str = "html") -> AnswerReportService: ...

    def indexing_service(self) -> IndexingService: ...

    def removal_service(self) -> RemovalService: ...

    def stats_service(self) -> StatsService: ...

    def stats_report_service(self) -> StatsReportService: ...

    def catalog_service(self) -> CatalogService: ...

    def dashboard_service(self, dashboard_format: str = "html") -> DashboardService: ...

    def live_watch_service(
        self, interval: float = 1.0, guard: AbstractContextManager[object] | None = None
    ) -> LiveWatchService: ...


def build_server(
    services: ServiceProvider, watch: Sequence[Path] = (), interval: float = 1.0
) -> MCPServer:
    """Creates an MCP server whose tools call the use cases from ``services``.

    Services are requested on every call so changes to the index on disk are picked up.
    With ``watch`` folders, the index follows their files (polled every ``interval``
    seconds) for as long as the server runs.
    """
    # Tools run in worker threads: one write at a time, tools and watcher alike, or two
    # writers would each save over the chunks of the other.
    writing = threading.Lock()
    bus = InMemorySubscriptionBus()
    lifespan = (
        _watching(lambda: services.live_watch_service(interval, writing).watch(watch), bus)
        if watch
        else None
    )
    server: MCPServer = MCPServer(
        SERVER_NAME,
        version=__version__,
        instructions=INSTRUCTIONS,
        subscriptions=bus,
        lifespan=lifespan,
    )

    @server.tool(
        title="Search documents",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
        meta=_view_meta(SEARCH_VIEW_URI),
    )
    def search_documents(query: str, top_k: int = 5) -> Annotated[CallToolResult, SearchOutput]:
        """Find the indexed passages that best match a query (BM25, no model call).

        Returns the passages ranked by score, each with its citation (file, page or
        Markdown section) so you can quote or open the source. Hosts that support MCP
        Apps also show the results with a score breakdown bar chart per passage.
        """
        report = services.search_report_service().search(_require(query, "query"), _clamp(top_k))
        results = report.results
        return _result(
            format_search_results(query, results),
            search_results_to_dict(query, results),
            report.content,
        )

    @server.resource(
        SEARCH_VIEW_URI,
        title="Search results view",
        description=(
            "MCP Apps view that shows the ranked passages returned by search_documents, "
            "with highlighted terms and a score breakdown per passage."
        ),
        mime_type=APP_MIME_TYPE,
        meta={"ui": {"prefersBorder": True}},
    )
    def search_view() -> str:
        return app_view("docsage search", __version__)

    @server.tool(
        title="Ask documents",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
        meta=_view_meta(ANSWER_VIEW_URI),
    )
    def ask_documents(question: str, top_k: int = 5) -> Annotated[CallToolResult, AnswerOutput]:
        """Answer a question from the indexed documents with Claude, citing sources.

        Retrieves the top_k passages and asks Claude for an answer grounded on them.
        Needs ANTHROPIC_API_KEY in the server's environment. Hosts that support MCP Apps
        also show an HTML report with the cited passages highlighted, from which the
        user can ask a follow-up question.
        """
        service = services.answer_report_service("html")
        report = service.report(_require(question, "question"), _clamp(top_k))
        return _result(format_answer(report.answer), answer_to_dict(report.answer), report.content)

    @server.resource(
        ANSWER_VIEW_URI,
        title="Answer report view",
        description=(
            "MCP Apps view that shows the HTML answer report returned by ask_documents, "
            "with a form to ask a follow-up question."
        ),
        mime_type=APP_MIME_TYPE,
        meta={"ui": {"prefersBorder": True}},
    )
    def answer_view() -> str:
        return app_view("docsage answer", __version__, ASK_FOLLOW_UP)

    @server.tool(
        title="Index path",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
    )
    def index_path(
        path: str, force: bool = False
    ) -> Annotated[CallToolResult, IndexingOutput]:
        """Index a file or a folder (recursively) so it can be searched.

        Supports Markdown, text and PDF. Files whose content has not changed since the
        last run are skipped unless force is true. Relative paths are resolved from the
        server's working directory.
        """
        target = _existing_path(path)
        with writing:
            report = services.indexing_service().index(expand_paths([target]), force=force)
        return _result(format_indexing_report(report), indexing_report_to_dict(report))

    @server.tool(
        title="Index URL",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True, open_world_hint=True
        ),
    )
    def index_url(url: str, force: bool = False) -> Annotated[CallToolResult, IndexingOutput]:
        """Fetch a web page (http or https) and index its main content.

        Navigation, headers and footers are dropped and the page is split on its
        headings; the URL becomes the citation. A page whose content has not changed
        since the last run is skipped unless force is true.
        """
        address = _web_address(url)
        with writing:
            report = services.indexing_service().index_urls([address], force=force)
        if report.failed:
            raise ToolError(f"Could not index {url}: {report.failed[0][1]}")
        return _result(format_indexing_report(report), indexing_report_to_dict(report))

    @server.tool(
        title="Remove URL",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True
        ),
    )
    def remove_url(url: str) -> Annotated[CallToolResult, RemovalOutput]:
        """Drop an indexed web page, and every indexed page below that URL, from the index."""
        address = _web_address(url)
        with writing:
            report = services.removal_service().remove_url(address)
        return _result(format_removal_report(url, report), removal_report_to_dict(url, report))

    @server.tool(
        title="Remove path",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True
        ),
    )
    def remove_path(path: str) -> Annotated[CallToolResult, RemovalOutput]:
        """Drop a file, or every file under a folder, from the index.

        Only the index changes; the files on disk are never touched.
        """
        target = Path(_require(path, "path"))
        with writing:
            report = services.removal_service().remove(target)
        return _result(
            format_removal_report(path, report), removal_report_to_dict(path, report)
        )

    @server.tool(
        title="Index stats",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
        meta=_view_meta(STATS_VIEW_URI),
    )
    def index_stats(top: int = 10) -> Annotated[CallToolResult, StatsOutput]:
        """Summarize the index: documents, chunks, terms, top terms and size on disk.

        Hosts that support MCP Apps also show the numbers as stat tiles with a bar chart
        of the top terms.
        """
        if top < 0:
            raise ToolError("top must not be negative")
        report = services.stats_report_service().report(min(top, MAX_TOP_TERMS))
        stats = report.stats
        return _result(format_stats(stats), stats_to_dict(stats), report.content)

    @server.resource(
        STATS_VIEW_URI,
        title="Index stats view",
        description=(
            "MCP Apps view that shows the stat tiles and top-terms bar chart returned by "
            "index_stats."
        ),
        mime_type=APP_MIME_TYPE,
        meta={"ui": {"prefersBorder": True}},
    )
    def stats_view() -> str:
        return app_view("docsage stats", __version__)

    @server.tool(
        title="Index dashboard",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
        meta=_view_meta(DASHBOARD_VIEW_URI),
    )
    def index_dashboard(top: int = 15) -> Annotated[CallToolResult, DashboardOutput]:
        """Chart the index: documents per file type, chunk lengths and top terms.

        Hosts that support MCP Apps show an interactive HTML dashboard; the text
        version carries the same numbers.
        """
        if top < 0:
            raise ToolError("top must not be negative")
        html = services.dashboard_service("html")
        overview = html.overview(min(top, MAX_TOP_TERMS))
        text = services.dashboard_service("text").render_overview(overview)
        return _result(text, overview_to_dict(overview), html.render_overview(overview))

    @server.resource(
        DASHBOARD_VIEW_URI,
        title="Index dashboard view",
        description="MCP Apps view that shows the HTML dashboard returned by index_dashboard.",
        mime_type=APP_MIME_TYPE,
        meta={"ui": {"prefersBorder": True}},
    )
    def dashboard_view() -> str:
        return app_view("docsage index", __version__)

    @server.resource(
        DOCUMENTS_URI,
        title="Indexed documents",
        description="Every indexed document with its chunk count, pages, sections and chunk ids.",
        mime_type="application/json",
    )
    def documents() -> str:
        summaries = services.catalog_service().documents()
        return dumps({"documents": [document_summary_to_dict(item) for item in summaries]})

    @server.resource(
        CHUNK_URI_TEMPLATE,
        title="Chunk",
        description="Full text and citation of one indexed chunk.",
        mime_type="application/json",
    )
    def chunk(chunk_id: str) -> str:
        found = services.catalog_service().chunk(chunk_id)
        if found is None:
            raise ResourceNotFoundError(f"No indexed chunk with id {chunk_id}")
        return dumps(chunk_to_dict(found))

    @server.prompt(title="Summarize document")
    def summarize_document(source: str) -> str:
        """Summarize one indexed document, citing its passages.

        source is the document path exactly as listed by docsage://documents.
        """
        passages = format_passages(_document_chunks(services, source), PROMPT_CHARACTERS)
        return (
            f"Summarize the document {source} using only the passages below. "
            "Start with a one-sentence overview, then list the key points. "
            "Cite the passages you rely on as [1], [2], ...\n\n"
            f"{passages}"
        )

    @server.prompt(title="Compare two documents")
    def compare_documents(first: str, second: str) -> str:
        """Compare two indexed documents: what they share, where they differ.

        first and second are document paths exactly as listed by docsage://documents.
        """
        budget = PROMPT_CHARACTERS // 2
        first_passages = format_passages(_document_chunks(services, first), budget, label="A")
        second_passages = format_passages(_document_chunks(services, second), budget, label="B")
        return (
            f"Compare document A ({first}) with document B ({second}) using only the "
            "passages below. Cover the topics both address, where they agree, where they "
            "differ or contradict each other, and what only one of them covers. "
            "Cite passages as [A1], [B2], ...\n\n"
            f"Document A: {first}\n\n{first_passages}\n\n"
            f"Document B: {second}\n\n{second_passages}"
        )

    return server


def _watching(
    updates: Callable[[], Iterator[WatchUpdate]], bus: SubscriptionBus
) -> Callable[[MCPServer], AbstractAsyncContextManager[None]]:
    """Server lifespan that applies file changes in the background while the server runs.

    The watcher blocks between changes, so it runs on a daemon thread that hands each
    index change back to the event loop; it never keeps the process alive on exit.
    """

    @asynccontextmanager
    async def lifespan(_: MCPServer) -> AsyncIterator[None]:
        stop = threading.Event()
        async with BlockingPortal() as portal:
            watcher = threading.Thread(
                target=_publish_updates,
                args=(updates, lambda: portal.call(_announce_change, bus), stop),
                name="docsage-watch",
                daemon=True,
            )
            watcher.start()
            try:
                yield
            finally:
                stop.set()
                await portal.stop(cancel_remaining=True)

    return lifespan


def _publish_updates(
    updates: Callable[[], Iterator[WatchUpdate]],
    announce: Callable[[], None],
    stop: threading.Event,
) -> None:
    """Applies watch updates until ``stop`` is set, announcing those that changed the index.

    A failing watcher is logged and stops watching; the server keeps serving.
    """
    try:
        for update in updates():
            if stop.is_set():
                return
            if update:
                announce()
    except Exception:
        if not stop.is_set():
            logger.exception("stopped watching for file changes")


async def _announce_change(bus: SubscriptionBus) -> None:
    """Tells listening clients that the document list changed."""
    await bus.publish(ResourcesListChanged())
    await bus.publish(ResourceUpdated(uri=DOCUMENTS_URI))


def format_passages(chunks: Sequence[Chunk], budget: int, label: str = "") -> str:
    """Numbers ``chunks`` as citable passages, stopping before ``budget`` characters."""
    blocks: list[str] = []
    used = 0
    for number, chunk in enumerate(chunks, start=1):
        block = f"[{label}{number}] {chunk.citation}\n{chunk.text.strip()}"
        if blocks and used + len(block) > budget:
            omitted = len(chunks) - len(blocks)
            blocks.append(f"[{omitted} more passages omitted to fit the prompt]")
            break
        blocks.append(block)
        used += len(block)
    return "\n\n".join(blocks)


def format_search_results(query: str, results: Sequence[SearchResult]) -> str:
    if not results:
        return f'No indexed passages match "{query}".'
    blocks = [f'{len(results)} passages for "{query}":']
    for rank, result in enumerate(results, start=1):
        matched = f"; matched: {', '.join(result.matched_terms)}" if result.matched_terms else ""
        blocks.append(
            f"[{rank}] {result.chunk.citation} (score {result.score:.2f}{matched})\n"
            f"{_preview(result.chunk.text)}"
        )
    return "\n\n".join(blocks)


def format_answer(answer: Answer) -> str:
    if not answer.sources:
        return answer.text
    sources = "\n".join(
        f"[{index}] {result.chunk.citation}"
        for index, result in enumerate(answer.sources, start=1)
    )
    text = f"{answer.text}\n\nSources:\n{sources}"
    if answer.usage is not None:
        text += f"\n\nUsage: {usage_summary(answer.usage, answer.cost_usd)}"
    return text


def format_indexing_report(report: IndexingReport) -> str:
    lines = [f"Indexed {report.documents} documents into {report.chunks} chunks."]
    if report.unchanged:
        lines.append(f"Skipped {report.unchanged} unchanged documents (pass force to re-index).")
    if report.skipped:
        lines.append(f"Skipped {len(report.skipped)} unsupported files:")
        lines.extend(f"  {path}" for path in report.skipped)
    if report.failed:
        lines.append(f"Could not index {len(report.failed)} pages:")
        lines.extend(f"  {url}: {reason}" for url, reason in report.failed)
    return "\n".join(lines)


def format_removal_report(path: str, report: RemovalReport) -> str:
    if not report.documents:
        return f"Nothing indexed under {path}."
    lines = [f"Removed {len(report.documents)} documents ({report.chunks} chunks):"]
    lines.extend(f"  {source}" for source in report.documents)
    return "\n".join(lines)


def format_stats(stats: IndexStats) -> str:
    lines = [
        f"Documents:  {stats.documents}",
        f"Chunks:     {stats.chunks}",
        f"Terms:      {stats.terms} ({stats.vocabulary} distinct)",
        f"Index size: {human_size(stats.index_bytes)}",
    ]
    if stats.top_terms:
        terms = ", ".join(f"{term} ({count})" for term, count in stats.top_terms)
        lines.append(f"Top terms: {terms}")
    return "\n".join(lines)


def _result(text: str, payload: dict[str, Any], html: str | None = None) -> CallToolResult:
    """Pairs the text the model reads with the structured content applications parse.

    ``html`` is a rendered page for the tool's MCP Apps view; it travels in ``_meta``,
    which hosts never add to the model's context.
    """
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=payload,
        _meta={HTML_META_KEY: html} if html is not None else None,
    )


def _view_meta(uri: str) -> dict[str, Any]:
    """Tool ``_meta`` linking the tool to its MCP Apps view."""
    return {"ui": {"resourceUri": uri}}


def _document_chunks(services: ServiceProvider, source: str) -> list[Chunk]:
    chunks = services.catalog_service().document_chunks(source)
    if not chunks:
        raise MCPError(
            INVALID_PARAMS,
            f"{source} is not indexed; read {DOCUMENTS_URI} for the indexed sources",
        )
    return chunks


def _existing_path(path: str) -> Path:
    target = Path(_require(path, "path"))
    if not target.exists():
        raise ToolError(f"{path} does not exist")
    return target


def _web_address(url: str) -> str:
    if not is_url(_require(url, "url")):
        raise ToolError(f"{url} is not an http(s) URL")
    return url


def _preview(text: str) -> str:
    flat = " ".join(text.split())
    if len(flat) <= PREVIEW_CHARACTERS:
        return flat
    return flat[:PREVIEW_CHARACTERS].rstrip() + "..."


def _require(value: str, name: str) -> str:
    if not value.strip():
        raise ToolError(f"{name} must not be empty")
    return value


def _clamp(top_k: int) -> int:
    if top_k < 1:
        raise ToolError("top_k must be at least 1")
    return min(top_k, MAX_TOP_K)
