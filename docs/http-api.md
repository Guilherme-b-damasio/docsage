# HTTP API, web UI and Docker

Run docsage as a server, for other programs or in a browser.

## HTTP API

`pip install -e ".[api]"` adds FastAPI and uvicorn, then `docsage serve` serves the index
over HTTP at `http://127.0.0.1:8000` (`--host` and `--port` to change it; global options
such as `--index`, `--retriever` and `--rerank` still apply). Responses use the same JSON
shapes as `--json`, and interactive docs are at `/docs`:

| Endpoint | Does |
| --- | --- |
| `POST /index` | `{"targets": ["docs/", "https://example.com/guide"], "force": false}`: index files, folders and pages |
| `GET /search?q=...&top_k=5&source=` | rank passages, with highlights and score breakdowns (no model call); `source` narrows the search |
| `POST /ask` | `{"question": "...", "top_k": 5, "source": ""}`: answer with Claude, with sources, usage and cost; `source` narrows the index it reads |
| `GET /stats?top=10` | summarize the index |
| `GET /health` | liveness check |

```bash
docsage serve --port 8000
curl -X POST localhost:8000/index -H "content-type: application/json" -d '{"targets": ["docs/"]}'
curl "localhost:8000/search?q=chunk%20size&top_k=3"
```

Only one indexing request writes at a time. `/ask` needs `ANTHROPIC_API_KEY` in the
server's environment.

## Web UI

The same server has a minimal web UI: open `http://127.0.0.1:8000/` in a browser. It is
built from the [visual reports](reports.md), so every page is a self-contained HTML document
that follows the system's light or dark mode:

| Page | Shows |
| --- | --- |
| `/ui?q=...&source=...` | a search form and the ranked passages with highlights and score breakdowns |
| `/ui/ask?q=...&source=...` | the answer report for a question ("Ask Claude" on the form) |
| `/ui/dashboard` | the index dashboard |
| `/ui/source?path=...` | an indexed document, opened from a citation |

The form has a **source** input next to the query (`/ui?q=...&source=docs/api`), which
narrows the search the same way `docsage search --source` does and stays filled in, so
the active filter is always visible. "Ask Claude" submits it too, so a question asked
from a filtered search is answered from that part of the index, and the report says so
above its sources.

Citations on the search and answer pages link to their source: web pages to their URL,
files to `/ui/source` (browsers do not open `file://` links from a web page), at the
right page for PDFs. It serves only documents that are in the index.

A Markdown or plain-text source is **rendered as an HTML page** with the cited passage
set off in place and its matched terms marked, from
`/ui/source?path=...&chunk=<id>&terms=<terms>#passage`: the server does the highlighting,
so every browser opens the citation at the passage, with the rest of the document around
it for context. A stale link (the document changed since it was indexed, or the chunk is
gone) still shows the document, just without a marked passage.

Sources the server does not render (PDFs, Word documents, HTML pages) are served as the
file itself, sandboxed so an indexed HTML page cannot run scripts against the API. Their
citations, and those of web pages, carry a
[text fragment](https://wicg.github.io/scroll-to-text-fragment/)
(`#:~:text=first words,last words&text=term`) pointing at the passage and the terms it
matched, so a browser that supports fragments (Chrome, Edge, Safari) still opens the
source at the cited passage; PDFs open at their page.

## Docker

The image serves the HTTP API and web UI on port 8000 with the `api`, `mcp` and `pdf`
extras installed (`--build-arg EXTRAS=api,mcp,pdf,embeddings` adds the embedding
retrievers). It runs as an unprivileged user in `/data`, where the index is stored, so
mount a volume there to keep it; a `docsage.toml` placed in `/data` is picked up too:

```bash
docker build -t docsage .
docker run --rm -p 8000:8000 -e ANTHROPIC_API_KEY -v docsage-index:/data -v "$PWD/docs:/docs:ro" docsage
```

`docker-compose.yml` does the same with a named volume and mounts `./docs` (or the folder
in `DOCSAGE_DOCS`) read-only at `/docs`. Any CLI command runs in a one-off container:

```bash
docker compose up --build -d
docker compose run --rm api index /docs
docker compose --profile mcp up -d
```

The `mcp` profile adds the MCP server over Streamable HTTP at `http://localhost:8765/mcp`,
sharing the index volume; index through one service at a time, since each process saves
the whole index.
