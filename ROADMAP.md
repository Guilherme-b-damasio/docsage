# Roadmap

Work through the milestones in order; inside a milestone, pick from the top.
Check items off as they land on `develop`. A milestone is done when all its items are checked.

The long-term goal is to turn docsage into an **MCP server** that any MCP client
(Claude Desktop, Claude Code, IDEs) can use to search and ask questions about local
documents, with **rich visual output**: dashboards, charts and highlighted citations.

## Done
- [x] Stopword lists for English and Portuguese in the tokenizer
- [x] Incremental indexing: skip files whose content hash has not changed
- [x] `docsage remove <path>` to drop a document from the index

## Milestone 0.2: Foundations for integrations
- [x] `--json` output for `search` and `ask` (shared serializers in `interfaces/`)
- [x] Config file support (`docsage.toml`) loaded into `Settings`
- [x] `docsage stats`: documents, chunks, tokens, top terms, index size
- [x] Store page numbers for PDF chunks and show them in citations
- [x] Markdown-aware chunker that splits on headings (keep the heading path as chunk metadata)
- [x] Structured logging with a `--verbose` flag
- [x] Type checking with mypy in CI
- [x] Test coverage report in CI

## Milestone 0.3: MCP server
- [x] Add the official `mcp` Python SDK as an optional extra (`docsage[mcp]`)
- [x] `interfaces/mcp_server.py` exposing tools: `search_documents`, `ask_documents`
- [x] MCP tools: `index_path`, `remove_path`, `index_stats`
- [x] MCP resources: list indexed documents (`docsage://documents`) and read a chunk by id
- [x] MCP prompts: "summarize document", "compare two documents"
- [x] `docsage mcp` CLI command that starts the server over stdio
- [x] Streamable HTTP transport option (`docsage mcp --http --port 8765`)
- [x] Integration tests driving the server with an in-memory MCP client
- [x] `docs/mcp.md`: setup for Claude Desktop and Claude Code (`claude mcp add`)
- [x] Return structured tool output (JSON schema) alongside text

## Milestone 0.4: Visual output
- [ ] Citation highlighting: return the matched terms and offsets for each chunk
- [ ] HTML report renderer for an answer (question, answer, cited passages with highlights)
- [ ] Index dashboard (HTML): documents per type, chunk length histogram, top terms
- [ ] Score breakdown chart per search result (BM25 term contributions)
- [ ] Serve visual output from the MCP server as UI resources (MCP Apps) where the client supports it, with a plain-text fallback
- [ ] `docsage report <question> --open` to render and open the HTML answer report
- [ ] Mermaid diagram of document relationships (shared top terms) in the dashboard
- [ ] Screenshots / GIF of the visual output in the README

## Milestone 0.5: Better retrieval
- [ ] Embedding-based retriever behind the `Retriever` port (local sentence-transformers model)
- [ ] Hybrid retriever that fuses BM25 and embedding scores (reciprocal rank fusion)
- [ ] Re-ranking step with Claude for the top-k candidates
- [ ] 2D map of chunk embeddings (UMAP/PCA) in the dashboard
- [ ] Retrieval evaluation script (recall@k, MRR on a small labeled set) with a results chart
- [ ] Sentence-boundary chunker

## Milestone 0.6: Generation and chat
- [ ] Stream answers to the terminal as they are generated
- [ ] Prompt caching for the context block
- [ ] Interactive chat mode with conversation history (`docsage chat`)
- [ ] Configurable answer language and length
- [ ] Token and cost report per answer

## Milestone 0.7: More sources and deployment
- [ ] HTML loader (strip tags, keep headings)
- [ ] DOCX loader
- [ ] Web page loader (fetch URL, extract main content)
- [ ] Watch mode: re-index a folder on file changes
- [ ] FastAPI HTTP server exposing `/index`, `/search`, `/ask`
- [ ] Minimal web UI reusing the HTML renderers
- [ ] Dockerfile and docker-compose example
- [ ] Publish to PyPI via GitHub Actions on release tags

## Quality (ongoing, pick when a milestone item is blocked)
- [ ] Benchmarks for indexing large folders
- [ ] Example corpus and a walkthrough in `docs/`
- [ ] Architecture decision records in `docs/adr/`
- [ ] Property-based tests for the chunkers (hypothesis)
