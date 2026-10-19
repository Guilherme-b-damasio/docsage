"""HTTP API. Thin layer like the CLI and the MCP server: validate the request, call a use
case, return the shared JSON shapes from ``docsage.interfaces.serializers``.

Requires the optional ``api`` extra (``pip install "docsage[api]"``).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Annotated, Any, Protocol

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

from docsage import __version__
from docsage.application.services import (
    IndexingService,
    QuestionAnsweringService,
    SearchService,
    StatsService,
)
from docsage.domain.models import is_url
from docsage.interfaces.paths import expand_paths
from docsage.interfaces.serializers import (
    answer_to_dict,
    indexing_report_to_dict,
    search_results_to_dict,
    stats_to_dict,
)

MAX_TOP_K = 50
MAX_TOP_TERMS = 100


class ServiceProvider(Protocol):
    """Builds the use cases the API calls; ``docsage.container.Container`` is one."""

    def search_service(self) -> SearchService: ...

    def question_answering_service(self) -> QuestionAnsweringService: ...

    def indexing_service(self) -> IndexingService: ...

    def stats_service(self) -> StatsService: ...


class IndexRequest(BaseModel):
    targets: list[str] = Field(
        min_length=1, description="Files, folders (indexed recursively) or http(s) URLs."
    )
    force: bool = Field(False, description="Re-index documents even if they have not changed.")


class AskRequest(BaseModel):
    question: str = Field(min_length=1)
    top_k: int = Field(5, ge=1, le=MAX_TOP_K)


def build_app(services: ServiceProvider) -> FastAPI:
    """Creates the API; services are requested per call so index changes are picked up."""
    app = FastAPI(
        title="docsage",
        version=__version__,
        description="Search and ask questions about your indexed documents.",
    )
    # Endpoints run in a thread pool: one write at a time, or two indexing runs would
    # each save over the chunks of the other.
    writing = threading.Lock()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/search")
    def search(
        q: Annotated[str, Query(min_length=1, description="The query.")],
        top_k: Annotated[int, Query(ge=1, le=MAX_TOP_K)] = 5,
    ) -> dict[str, Any]:
        """Ranks the indexed passages against ``q`` (no model call)."""
        return search_results_to_dict(q, services.search_service().search(q, top_k))

    @app.get("/stats")
    def stats(top: Annotated[int, Query(ge=0, le=MAX_TOP_TERMS)] = 10) -> dict[str, Any]:
        """Documents, chunks, terms, top terms and index size."""
        return stats_to_dict(services.stats_service().stats(top))

    @app.post("/index")
    def index(request: IndexRequest) -> dict[str, Any]:
        """Indexes files, folders and web pages; unchanged documents are skipped."""
        urls = [target for target in request.targets if is_url(target)]
        paths = [Path(target) for target in request.targets if not is_url(target)]
        missing = [str(path) for path in paths if not path.exists()]
        if missing:
            raise HTTPException(404, f"No such file or folder: {', '.join(missing)}")
        with writing:
            service = services.indexing_service()
            report = service.index(expand_paths(paths), force=request.force)
            if urls:
                report = report.combined_with(service.index_urls(urls, force=request.force))
        return indexing_report_to_dict(report)

    @app.post("/ask")
    def ask(request: AskRequest) -> dict[str, Any]:
        """Answers the question with Claude from the best ``top_k`` passages, with sources."""
        if not request.question.strip():
            raise HTTPException(422, "question must not be blank")
        answer = services.question_answering_service().ask(request.question, request.top_k)
        return answer_to_dict(answer)

    return app
