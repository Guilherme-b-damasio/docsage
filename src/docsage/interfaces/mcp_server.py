"""MCP server. Thin layer like the CLI: validate arguments, call a use case, format text.

Requires the optional ``mcp`` extra (``pip install "docsage[mcp]"``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from docsage import __version__
from docsage.application.services import QuestionAnsweringService, SearchService
from docsage.domain.models import Answer, SearchResult

SERVER_NAME = "docsage"
INSTRUCTIONS = (
    "Search and ask questions about the user's locally indexed documents. "
    "Use search_documents to find passages and ask_documents for a cited answer."
)
MAX_TOP_K = 50
PREVIEW_CHARACTERS = 400


class ServiceProvider(Protocol):
    """Builds the use cases the server calls; ``docsage.container.Container`` is one."""

    def search_service(self) -> SearchService: ...

    def question_answering_service(self) -> QuestionAnsweringService: ...


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

    return server


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
