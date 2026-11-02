# Tuning retrieval

How docsage finds passages, and how to measure and improve it.

## Chunking

The default `window` chunker cuts text into windows of `chunk_size` words that share
`chunk_overlap` words. The `sentence` chunker packs whole sentences into chunks of at most
`chunk_size` words and repeats the previous chunk's last sentences (up to `chunk_overlap`
words), so passages never stop mid-sentence. Markdown is first split on headings with
either one. Blank lines end a sentence too, and common abbreviations such as "e.g." do
not. Unchanged files keep their chunks, so re-index with `--force` after switching:

```bash
docsage index docs/ --chunker sentence --force
```

## Retrievers

BM25 (the default) ranks by shared words and needs no extra packages. Common English and
Portuguese stopwords are ignored when ranking, so questions phrased in either language
match on their content words.

For matches on
meaning rather than exact words, install the embeddings extra and pick the
`embedding` retriever, which ranks chunks by the cosine similarity of their vectors
from a local [sentence-transformers](https://www.sbert.net/) model:

```bash
pip install -e ".[embeddings]"
docsage --retriever embedding search "how do I keep the index small?"
```

Both retrievers read the same index, so you can switch at any time without
re-indexing. Chunks are embedded on the first search and their vectors are cached
next to the index (`index.embeddings.json`), so later runs only embed new or changed
chunks. Embedding results have no per-term score breakdown.

`--retriever hybrid` runs both and fuses their rankings with
[reciprocal rank fusion](https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf):
each chunk scores `sum(1 / (60 + rank))` over the rankings it appears in, so passages
that match both the words and the meaning of the question come first, and a passage
only one retriever finds still makes the list. Scores are fused ranks, so hybrid
results have no per-term breakdown either.

## Re-ranking with Claude

`--rerank` (or `rerank = true`) adds a second stage to `search`, `ask`, `report` and
the MCP tools: the retriever proposes its best `rerank_candidates` passages, Claude
grades each one from 0 to 10 for how well it answers the query, and the passages are
returned best grade first (ties keep the retriever's order). The score shown is the
grade. It works on top of any retriever and needs Claude API credentials:

```bash
docsage --retriever hybrid --rerank search "how do I keep the index small?"
```

## Evaluating retrieval

`docsage evaluate` measures how well the configured retriever finds the right documents.
Give it a JSON file of labeled queries, each with the sources that answer it (full paths or
path suffixes such as `docs/install.md`):

```json
[{"query": "where is the index stored", "relevant": ["faq.txt"]}]
```

It reports recall@k (the share of relevant documents found in the top k chunks), the
mean reciprocal rank of the first relevant chunk and where each query's first hit landed.
`--format html` draws recall at every cut-off and each query's reciprocal rank as charts;
`--format json` returns the same numbers for scripts. Combine it with `--retriever` and
`--rerank` to compare strategies on the same labels:

```bash
docsage index tests/fixtures/corpus
docsage evaluate tests/fixtures/evaluation.json -k 3
docsage --retriever hybrid evaluate tests/fixtures/evaluation.json --format html -o eval.html
```
