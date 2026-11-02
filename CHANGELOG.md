# Changelog

## What's new in 0.9

- Clickable source links on the HTML search results page and in the web UI.
- An MCP Apps view for `index_stats`, with stat tiles and a top-terms bar chart.
- A follow-up question can be asked straight from the answer report view, which calls
  `ask_documents` again through the host.
- `search_documents source`, `docsage search --source` and `GET /search?source=` narrow
  a search to a file type, a folder or a URL prefix.
- Citations of HTML, Markdown, text and web sources open at the cited passage, with its
  matched terms highlighted, through a browser text fragment.

## What's new in 0.8

- `docsage mcp --watch <folder>` keeps the index in sync while serving and tells MCP
  clients that `docsage://documents` changed.
- `search_documents` results show up in an MCP Apps view with score breakdown bars.
- Every cited passage in the HTML answer report links to its source file, PDF page or
  URL, and the MCP Apps view asks the host to open those links.
- `docsage report --format markdown` exports the answer report as Markdown.
- The dashboard lists the most recently indexed documents with their chunk counts.

## What's new in 0.7

- HTML (`.html`, `.htm`) and Word (`.docx`) loaders, and web pages by URL
  (`docsage index https://...`, MCP `index_url` / `remove_url`), main content only.
- `docsage watch` keeps the index in sync with folders as files change.
- `docsage serve` exposes `/index`, `/search`, `/ask` and `/stats` over HTTP
  (`docsage[api]`), with a web UI under `/ui` built from the HTML renderers.
- A Dockerfile and a `docker-compose.yml` with the API and an optional MCP service.
- Version tags are published to PyPI by GitHub Actions with trusted publishing.

## What's new in 0.6

- `ask` streams the answer as Claude writes it (`--no-stream` to wait for the whole text).
- The passages sent to Claude are cached, so follow-ups on the same context cost less
  (`prompt_cache = false` to turn it off).
- `docsage chat` keeps the conversation, so follow-up questions make sense.
- `--language` and `--length` (or `answer_language` / `answer_length`) fix how answers read.
- Every answer reports its token usage and estimated cost (`--usage`, JSON, MCP and the
  HTML report).

## What's new in 0.5

- `embedding` and `hybrid` retrievers (`--retriever`, `docsage[embeddings]`): local
  sentence-transformers vectors, fused with BM25 by reciprocal rank fusion.
- `--rerank` lets Claude grade and reorder the best candidates of any retriever.
- The dashboard maps chunk embeddings in 2D (PCA) when an embedding retriever is used.
- `docsage evaluate` measures recall@k and MRR on a labeled query set, as text, JSON or
  an HTML page with charts.
- `index --chunker sentence` keeps every sentence whole inside its chunk.

## What's new in 0.4

- Search results and answers carry highlight offsets and a per-term BM25 score
  breakdown (`search --explain`, JSON and MCP structured output).
- `docsage report` renders an answer as a self-contained HTML page with highlighted
  citations and score charts; `--open` shows it in the browser.
- `docsage dashboard`: an offline HTML dashboard of the index with charts of file
  types, chunk lengths, top terms and a graph of related documents
  (`--format text` and `--format mermaid` too).
- In MCP Apps hosts, `ask_documents` and the new `index_dashboard` tool show those
  HTML pages right in the conversation, following the host's light or dark theme;
  other clients get the same content as text.

## What's new in 0.3

- `docsage mcp` turns the index into an MCP server over stdio, or Streamable HTTP
  with `--http`.
- Tools to search, ask, index, remove and summarize the index, each with an output
  schema and structured content next to the text.
- `docsage://documents` and `docsage://chunks/{chunk_id}` resources, plus
  `summarize_document` and `compare_documents` prompts.
- [docs/mcp.md](docs/mcp.md): setup for Claude Code, Claude Desktop and HTTP clients.
- An integration suite drives the server with an in-memory MCP client.

## What's new in 0.2

- `--json` output for `search`, `ask` and `stats`, for scripts and other tools.
- `docsage.toml` config file for the index path, chunking and model.
- `docsage stats`: documents, chunks, terms, top terms and index size.
- Citations with PDF page numbers and Markdown heading paths; Markdown is chunked
  by section.
- `--verbose` structured (`key=value`) logging on stderr.
- CI runs strict mypy and reports test coverage.
