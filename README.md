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
summary), handy for scripts and other tools.

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

### MCP server (in progress)

`pip install -e ".[mcp]"` adds the official MCP SDK. `docsage.interfaces.mcp_server`
builds a server with these tools:

| Tool               | What it does                                              |
| ------------------ | --------------------------------------------------------- |
| `search_documents` | ranked passages with citations, no model call             |
| `ask_documents`    | a cited answer from Claude (needs `ANTHROPIC_API_KEY`)    |
| `index_path`       | index a file or folder; unchanged files are skipped       |
| `remove_path`      | drop a file or folder from the index (files stay on disk) |
| `index_stats`      | documents, chunks, top terms and index size               |

It also publishes two read-only resources (JSON):

| Resource                      | Contents                                                     |
| ----------------------------- | ------------------------------------------------------------ |
| `docsage://documents`         | every indexed document: chunk count, pages, sections, chunk ids |
| `docsage://chunks/{chunk_id}` | the full text, position and citation of one chunk            |

A `docsage mcp` command to start it over stdio is next on the [roadmap](ROADMAP.md).

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
├── application/      use cases: indexing, removal, stats, question answering
├── infrastructure/   adapters: file loaders, chunker, BM25 retriever, Claude generator
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

The project uses [git flow](CONTRIBUTING.md). See the [roadmap](ROADMAP.md) for planned work.

## License

MIT
