"""HTTP API. Thin layer like the CLI and the MCP server: validate the request, call a use
case, return the shared JSON shapes from ``docsage.interfaces.serializers``.

It also serves a minimal web UI under ``/ui`` built from the same HTML renderers as
``docsage report`` and ``docsage dashboard``: a search page, answer reports and the dashboard.

Requires the optional ``api`` extra (``pip install "docsage[api]"``).
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Annotated, Any, Protocol

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import BaseModel, Field

from docsage import __version__
from docsage.application.services import (
    AnswerReportService,
    DashboardService,
    IndexingService,
    QuestionAnsweringService,
    SearchReportService,
    SearchService,
    StatsService,
)
from docsage.domain.models import is_url
from docsage.infrastructure.html_search import PageLinks
from docsage.interfaces.paths import expand_paths
from docsage.interfaces.serializers import (
    answer_to_dict,
    indexing_report_to_dict,
    search_results_to_dict,
    stats_to_dict,
)

MAX_TOP_K = 50
MAX_TOP_TERMS = 100

UI_LINKS = PageLinks(search="/ui", ask="/ui/ask", dashboard="/ui/dashboard")


class ServiceProvider(Protocol):
    """Builds the use cases the API calls; ``docsage.container.Container`` is one."""

    def search_service(self) -> SearchService: ...

    def question_answering_service(self) -> QuestionAnsweringService: ...

    def indexing_service(self) -> IndexingService: ...

    def stats_service(self) -> StatsService: ...

    def search_report_service(self, links: PageLinks | None = None) -> SearchReportService: ...

    def answer_report_service(self, report_format: str = "html") -> AnswerReportService: ...

    def dashboard_service(self, dashboard_format: str = "html") -> DashboardService: ...


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

    _add_web_ui(app, services)
    return app


def _add_web_ui(app: FastAPI, services: ServiceProvider) -> None:
    """HTML pages for a browser; every page is self-contained and works offline."""

    @app.get("/", include_in_schema=False)
    def home() -> RedirectResponse:
        return RedirectResponse(UI_LINKS.search)

    @app.get("/ui", response_class=HTMLResponse, tags=["web UI"])
    def search_page(
        q: Annotated[str, Query(description="The query; empty shows only the form.")] = "",
        top_k: Annotated[int, Query(ge=1, le=MAX_TOP_K)] = 5,
    ) -> str:
        """A search form and the ranked passages with highlights and score breakdowns."""
        return services.search_report_service(UI_LINKS).report(q, top_k)

    @app.get("/ui/ask", response_class=HTMLResponse, tags=["web UI"], response_model=None)
    def answer_page(
        q: Annotated[str, Query(description="The question.")] = "",
        top_k: Annotated[int, Query(ge=1, le=MAX_TOP_K)] = 5,
    ) -> str | RedirectResponse:
        """The answer report: Claude's answer with its highlighted, cited passages."""
        if not q.strip():
            return RedirectResponse(UI_LINKS.search)
        return services.answer_report_service("html").report(q.strip(), top_k).content

    @app.get("/ui/dashboard", response_class=HTMLResponse, tags=["web UI"])
    def dashboard_page() -> str:
        """Documents per type, chunk lengths, top terms and document relationships."""
        return services.dashboard_service("html").render()
