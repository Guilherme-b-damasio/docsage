# docsage

Ask questions about your own documents. `docsage` indexes Markdown, text and PDF
files, retrieves the most relevant passages with BM25, and asks Claude for an
answer that cites its sources. Common English and Portuguese stopwords are ignored
when ranking, so questions phrased in either language match on their content words.

```bash
pip install -e ".[pdf]"
docsage index ./docs
docsage search "how is the index persisted?"
docsage ask "what chunking strategy does the project use?"
docsage remove ./docs/old-notes.md   # or a whole folder
docsage stats                        # documents, chunks, top terms, index size
```

Markdown files are split on their headings, so a chunk never mixes two sections,
and long sections are windowed like any other text. Citations point to where a
passage came from: the heading path for Markdown (`guide.md, Setup > Install`) and
the page for PDFs (`guide.pdf, p. 4` or `guide.pdf, pp. 4-5`), both in the terminal
output and in the passages sent to Claude.

Re-running `index` only processes files whose content changed since the last run;
pass `--force` to rebuild every document.

`search`, `ask` and `stats` accept `--json` to print machine-readable output
(ranked chunks with scores, the answer with its cited sources, or the index
summary), handy for scripts and other tools. Each ranked chunk lists its
`matched_terms` and `highlights`: the character offsets in the chunk's text where
a query term occurs (`{"start": 4, "end": 9, "term": "index"}`), normalized the same
way the ranking is, so a viewer can highlight exactly what matched.
Results also carry `contributions`, the BM25 score split by query term
(`{"term": "index", "score": 1.42}`, largest first, summing to `score`), so you can see
why a passage ranked where it did; `docsage search "query" --explain` prints the same
breakdown under each result, and the HTML answer report charts it for every source.

Add `-v`/`--verbose` before the command to log what docsage is doing to stderr,
one `key=value` line per event (documents indexed or skipped, index loads and
saves, retrieval counts, Claude token usage), so stdout stays clean for `--json`:

```bash
docsage --verbose index ./docs
# level=debug logger=docsage.application.services event="indexed document" source=docs/a.md chunks=3
```

### Configuration

Put a `docsage.toml` in the folder you run `docsage` from (or pass `--config path`)
to change the defaults. Every key is optional; command-line flags win over the file.

```toml
index_path = ".docsage/index.json"   # relative paths are resolved from this file's folder
chunk_size = 200                     # words per chunk
chunk_overlap = 40                   # words shared between consecutive chunks
model = "claude-opus-5-5"            # model used by `ask`
```

`ask` uses the Claude API. Set `ANTHROPIC_API_KEY` (or log in with `ant auth login`)
before running it. `index` and `search` work offline.

### MCP server

`pip install -e ".[mcp]"` adds the official MCP SDK, then `docsage mcp` serves the
index over stdio (global options such as `--index` and `--config` still apply; logs
go to stderr so stdout stays reserved for the protocol):

```bash
docsage --index ~/notes/.docsage/index.json mcp
claude mcp add docsage -- docsage --index ~/notes/.docsage/index.json mcp
```

For clients that connect over the network, `--http` serves Streamable HTTP instead
(default `127.0.0.1:8765`, endpoint `/mcp`; `--host` and `--port` change it):

```bash
docsage --index ~/notes/.docsage/index.json mcp --http --port 8765
claude mcp add --transport http docsage http://127.0.0.1:8765/mcp
```

The server offers these tools:

| Tool               | What it does                                              |
| ------------------ | --------------------------------------------------------- |
| `search_documents` | ranked passages with citations, no model call             |
| `ask_documents`    | a cited answer from Claude (needs `ANTHROPIC_API_KEY`)    |
| `index_path`       | index a file or folder; unchanged files are skipped       |
| `remove_path`      | drop a file or folder from the index (files stay on disk) |
| `index_stats`      | documents, chunks, top terms and index size               |
| `index_dashboard`  | charts of file types, chunk lengths, top terms and related documents |

In hosts that support [MCP Apps](https://github.com/modelcontextprotocol/ext-apps),
`ask_documents` shows the HTML answer report with highlighted citations and
`index_dashboard` the HTML dashboard, right in the conversation; other hosts get the
same content as text.

It also publishes two read-only resources (JSON), plus the two `ui://` views:

| Resource                      | Contents                                                     |
| ----------------------------- | ------------------------------------------------------------ |
| `docsage://documents`         | every indexed document: chunk count, pages, sections, chunk ids |
| `docsage://chunks/{chunk_id}` | the full text, position and citation of one chunk            |

And two prompts that embed whole documents as numbered, citable passages
(about 60k characters at most; the rest is left out and the prompt says so):

| Prompt               | Arguments         | Asks for                                         |
| -------------------- | ----------------- | ------------------------------------------------ |
| `summarize_document` | `source`          | an overview and key points, citing `[1]`, `[2]`  |
| `compare_documents`  | `first`, `second` | shared topics, agreements, differences (`[A1]`, `[B2]`) |

Pass sources exactly as `docsage://documents` lists them.

Every tool also publishes an output schema and returns `structuredContent` with the
same fields as the CLI's `--json` output, so agents can read scores, citations and
counts without parsing the text.

[docs/mcp.md](docs/mcp.md) walks through the Claude Code, Claude Desktop and HTTP
setup, with every tool's arguments and a troubleshooting list.

### Visual reports

An answer can be rendered as a single, self-contained HTML page: the question, the
answer with each `[n]` citation linked to its passage, and every cited passage with
the matched query terms highlighted. The page inlines its CSS (no network needed) and
follows the system's light or dark mode. A plain-text renderer is the fallback for
clients that cannot show HTML (matched terms appear in `**bold**`).

`docsage report` answers a question with Claude and writes the report: to stdout by
default, to a file with `-o`, or as plain text with `--format text`. `--open` shows it in
the default browser (in a temporary file unless `-o` is given):

```bash
docsage report "How does BM25 work?" --open
docsage report "How does BM25 work?" -o reports/bm25.html
```

![Answer report: the answer with linked citations, then each cited passage with its matched terms highlighted and a score breakdown chart](docs/images/answer-report-light.png)

From Python:

```python
from pathlib import Path

from docsage.container import Container, load_settings

report = Container(load_settings()).answer_report_service("html").report("How does BM25 work?")
Path("answer.html").write_text(report.content, encoding="utf-8")
```

### Index dashboard

`docsage dashboard` writes a single-file HTML dashboard of the index: totals, documents
per file type, a histogram of chunk lengths (in words) and the most frequent terms. The
charts are inline SVG, so the page works offline, follows light and dark mode, shows
each value on hover and has a "Show as table" view under every chart.

A "Related documents" graph links documents that share characteristic terms (frequent
in the document, rare across the index), with thicker lines for more shared terms. Its
Mermaid source is one click away, and `--format mermaid` prints just that diagram, ready
to paste into a Markdown file or a GitHub issue.

```bash
docsage dashboard -o dashboard.html     # then open it in a browser
docsage dashboard --format text         # the same numbers as text bars in the terminal
docsage dashboard --format mermaid      # related documents as a Mermaid graph
```

![Index dashboard in dark mode: stat tiles, documents per file type, chunk lengths, top terms and the related documents graph](docs/images/dashboard-dark.png)

`python scripts/screenshots.py` regenerates both screenshots from this repository's own
docs with a headless Chrome or Edge and a canned answer, so it needs no API key.

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

## Architecture

The code follows a ports-and-adapters (hexagonal) layout:

```
src/docsage/
├── domain/           entities (Document, Chunk, Answer) and ports (Protocols)
├── application/      use cases: indexing, removal, stats, question answering, reports
├── infrastructure/   adapters: file loaders, chunker, BM25 retriever, Claude generator,
│                     HTML and plain-text renderers
├── interfaces/       CLI, MCP server and shared JSON serializers
└── container.py      composition root, wires adapters to ports
```

- **Single responsibility.** Each adapter does one job: loading, chunking, ranking or generating.
- **Open/closed.** New file formats or retrievers are new classes that implement a port. Existing code stays untouched.
- **Dependency inversion.** Use cases depend on the Protocols in `domain/ports.py`, never on concrete adapters. That is why the tests can swap in fakes without mocking libraries.

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check .
mypy          # strict type checking of src/, also run in CI
pytest --cov  # coverage report; CI fails below 90% and publishes the summary
```

`tests/unit/` covers each class with fakes. `tests/integration/` drives the MCP server
end to end: one in-memory client session indexes the small corpus in
`tests/fixtures/corpus/`, reads resources, searches, asks and removes, against a real
on-disk index. Only the answer generator is faked (`Container(settings, generator)`),
so no test calls the Claude API.

The project uses [git flow](CONTRIBUTING.md). See the [roadmap](ROADMAP.md) for planned work.

## License

MIT
