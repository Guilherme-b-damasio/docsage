"""MCP server. Thin layer like the CLI: validate arguments, call a use case, format text.

Requires the optional ``mcp`` extra (``pip install "docsage[mcp]"``).
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from mcp import MCPError
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
from mcp.types import INVALID_PARAMS, ToolAnnotations

from docsage import __version__
from docsage.application.services import (
    CatalogService,
    IndexingReport,
    IndexingService,
    IndexStats,
    QuestionAnsweringService,
    RemovalReport,
    RemovalService,
    SearchService,
    StatsService,
)
from docsage.domain.models import Answer, Chunk, SearchResult
from docsage.interfaces.paths import expand_paths
from docsage.interfaces.serializers import chunk_to_dict, document_summary_to_dict, dumps
from docsage.interfaces.text import human_size

SERVER_NAME = "docsage"
DOCUMENTS_URI = "docsage://documents"
CHUNK_URI_TEMPLATE = "docsage://chunks/{chunk_id}"
INSTRUCTIONS = (
    "Search and ask questions about the user's locally indexed documents. "
    "Use search_documents to find passages and ask_documents for a cited answer. "
    "index_path adds files or folders, remove_path drops them, index_stats summarizes. "
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

    def search_service(self) -> SearchService: ...

    def question_answering_service(self) -> QuestionAnsweringService: ...

    def indexing_service(self) -> IndexingService: ...

    def removal_service(self) -> RemovalService: ...

    def stats_service(self) -> StatsService: ...

    def catalog_service(self) -> CatalogService: ...


def build_server(services: ServiceProvider) -> MCPServer:
    """Creates an MCP server whose tools call the use cases from ``services``.

    Services are requested on every call so changes to the index on disk are picked up.
    """
    server: MCPServer = MCPServer(SERVER_NAME, version=__version__, instructions=INSTRUCTIONS)

    @server.tool(
        title="Search documents",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
        structured_output=False,
    )
    def search_documents(query: str, top_k: int = 5) -> str:
        """Find the indexed passages that best match a query (BM25, no model call).

        Returns the passages ranked by score, each with its citation (file, page or
        Markdown section) so you can quote or open the source.
        """
        results = services.search_service().search(_require(query, "query"), _clamp(top_k))
        return format_search_results(query, results)

    @server.tool(
        title="Ask documents",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=True),
        structured_output=False,
    )
    def ask_documents(question: str, top_k: int = 5) -> str:
        """Answer a question from the indexed documents with Claude, citing sources.

        Retrieves the top_k passages and asks Claude for an answer grounded on them.
        Needs ANTHROPIC_API_KEY in the server's environment.
        """
        service = services.question_answering_service()
        answer = service.ask(_require(question, "question"), _clamp(top_k))
        return format_answer(answer)

    @server.tool(
        title="Index path",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=False, idempotent_hint=True
        ),
        structured_output=False,
    )
    def index_path(path: str, force: bool = False) -> str:
        """Index a file or a folder (recursively) so it can be searched.

        Supports Markdown, text and PDF. Files whose content has not changed since the
        last run are skipped unless force is true. Relative paths are resolved from the
        server's working directory.
        """
        target = _existing_path(path)
        report = services.indexing_service().index(expand_paths([target]), force=force)
        return format_indexing_report(report)

    @server.tool(
        title="Remove path",
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True
        ),
        structured_output=False,
    )
    def remove_path(path: str) -> str:
        """Drop a file, or every file under a folder, from the index.

        Only the index changes; the files on disk are never touched.
        """
        report = services.removal_service().remove(Path(_require(path, "path")))
        return format_removal_report(path, report)

    @server.tool(
        title="Index stats",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
        structured_output=False,
    )
    def index_stats(top: int = 10) -> str:
        """Summarize the index: documents, chunks, terms, top terms and size on disk."""
        if top < 0:
            raise ToolError("top must not be negative")
        return format_stats(services.stats_service().stats(min(top, MAX_TOP_TERMS)))

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
        blocks.append(
            f"[{rank}] {result.chunk.citation} (score {result.score:.2f})\n"
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
    return f"{answer.text}\n\nSources:\n{sources}"


def format_indexing_report(report: IndexingReport) -> str:
    lines = [f"Indexed {report.documents} documents into {report.chunks} chunks."]
    if report.unchanged:
        lines.append(f"Skipped {report.unchanged} unchanged documents (pass force to re-index).")
    if report.skipped:
        lines.append(f"Skipped {len(report.skipped)} unsupported files:")
        lines.extend(f"  {path}" for path in report.skipped)
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
