# Roadmap

Work is picked from the top of each section. Check items off as they land on `develop`.

## Retrieval
- [ ] Embedding-based retriever behind the `Retriever` port (local sentence-transformers model)
- [ ] Hybrid retriever that fuses BM25 and embedding scores (reciprocal rank fusion)
- [ ] Re-ranking step with Claude for the top-k candidates
- [ ] Stopword lists for English and Portuguese in the tokenizer
- [ ] Incremental indexing: skip files whose content hash has not changed
- [ ] `docsage remove <path>` to drop a document from the index

## Ingestion
- [ ] HTML loader (strip tags, keep headings)
- [ ] DOCX loader
- [ ] Markdown-aware chunker that splits on headings
- [ ] Sentence-boundary chunker
- [ ] Store page numbers for PDF chunks and show them in citations

## Generation
- [ ] Stream answers to the terminal as they are generated
- [ ] Interactive chat mode with conversation history (`docsage chat`)
- [ ] Prompt caching for the context block
- [ ] Configurable answer language and length

## Interfaces
- [ ] Config file support (`docsage.toml`)
- [ ] `--json` output for `search` and `ask`
- [ ] FastAPI HTTP server exposing `/index`, `/search`, `/ask`
- [ ] Minimal web UI
- [ ] Dockerfile

## Quality
- [ ] Retrieval evaluation script (recall@k on a small labeled set)
- [ ] Test coverage report in CI
- [ ] Type checking with mypy in CI
- [ ] Benchmarks for indexing large folders
- [ ] Example corpus and a walkthrough in `docs/`
