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

Re-running `index` only processes files whose content changed since the last run;
pass `--force` to rebuild every document.

`search`, `ask` and `stats` accept `--json` to print machine-readable output
(ranked chunks with scores, the answer with its cited sources, or the index
summary), handy for scripts and other tools.

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

## Architecture

The code follows a ports-and-adapters (hexagonal) layout:

```
src/docsage/
├── domain/           entities (Document, Chunk, Answer) and ports (Protocols)
├── application/      use cases: indexing, removal, stats, question answering
├── infrastructure/   adapters: file loaders, chunker, BM25 retriever, Claude generator
├── interfaces/       CLI and shared JSON serializers
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
```

The project uses [git flow](CONTRIBUTING.md). See the [roadmap](ROADMAP.md) for planned work.

## License

MIT
