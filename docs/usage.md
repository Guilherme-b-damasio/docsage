# Using docsage

Everyday use of the command line: indexing, asking and configuring.

## What gets indexed

Markdown files are split on their headings, so a chunk never mixes two sections,
and long sections are windowed like any other text. HTML pages (`.html`, `.htm`) get
the same treatment: tags, scripts and styles are stripped, `<h1>`-`<h6>` become the
section headings and `<pre>` blocks keep their lines; it uses only the standard library.
Word documents (`.docx`) are read the same way, also without extra dependencies:
paragraphs styled as headings (or with an outline level, so localized styles such as
"Título 1" work too) become the sections, and table rows become `cell | cell` lines.
Citations point to where a passage came from: the heading path for Markdown, HTML and
Word (`guide.md, Setup > Install`) and
the page for PDFs (`guide.pdf, p. 4` or `guide.pdf, pp. 4-5`), both in the terminal
output and in the passages sent to Claude.

## Re-indexing

Re-running `index` only processes files whose content changed since the last run;
pass `--force` to rebuild every document.

## Web pages

`index` also takes `http://` and `https://` URLs, mixed with paths. The page is fetched
with the standard library (up to 5 MB, 15 s timeout), and for HTML only the main content
is kept: the `<main>` element, or the `<article>` elements without one, with navigation,
headers, footers, sidebars and forms dropped. It then splits on its headings like a local
page and is cited by URL (`https://example.com/guide, Setup > Install`). Markdown and
plain-text URLs are kept as they are. Pages that cannot be fetched are listed as failed
(and `index` exits with 1) while the rest is still indexed; `docsage remove <url>` drops
a page and every indexed page below that URL. The dashboard counts them as `web`.

## Keeping the index in sync

`docsage watch <folder>...` indexes the folders like `index` and then keeps the index in
sync while it runs: files that are created or edited are re-indexed, deleted files are
dropped from the index, and unchanged files are skipped by their content hash. It polls
the files every second (`--interval 0.5` to look more often), needs no extra packages,
never looks inside the index's own folder (unless the watched folder is in it), and
stops with Ctrl-C:

```bash
docsage watch docs/ notes.md
# Watching docs, notes.md for changes (Ctrl-C to stop).
# Indexed 12 documents into 87 chunks.
# Indexed 1 documents into 4 chunks.
# Removed docs/old.md.
```

## Searching part of the index

`--source <pattern>` works on `search`, `ask` and `report` alike: it reads only part of
the index, either a file type (`.md`, `*.pdf`), a folder or path (`docs`, `docs/api`,
matched against the source's folders) or a web address prefix
(`https://example.com/docs`). The pattern ignores case and accepts either slash, and a
narrow filter can return fewer than `--top-k` passages:

```bash
docsage search "chunk size" --source docs/api
docsage search "chunk size" --source .pdf
docsage ask "how big should a chunk be?" --source docs/api
```

A narrowed answer is grounded only on those sources, so it speaks for that part of the
index alone; when nothing there matches the question, Claude is not called at all.
Every rendered page says which part of the index it read, e.g. *3 matching passages in
`docs/api`* or *Answered from 2 passages in `docs/api`*, so a short result list is never
a mystery; the web UI's search page also links back to the whole index.

## Asking questions

`ask` uses the Claude API. Set `ANTHROPIC_API_KEY` (or log in with `ant auth login`)
before running it. `index` and `search` work offline. The answer is streamed to the
terminal as Claude writes it, followed by the list of sources; pass `--no-stream` to
print it only once it is complete (`--json` output is never streamed).
The passages are sent to Claude as their own block, marked for
[prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), with the
question after them, so asking again over the same passages within a few minutes reads them
from the cache instead of paying for them in full. `--verbose` logs
`cache_creation_input_tokens` and `cache_read_input_tokens` for each answer; set
`prompt_cache = false` in `docsage.toml` to turn it off. Context shorter than the model's
minimum cacheable prefix is simply not cached.

### Language and length

By default Claude answers in the language of the question, at whatever length the passages
call for. `--language` (any language name Claude understands, e.g. `Portuguese`) makes every
answer use that language whatever the question's, and `--length short` keeps it to two or
three sentences while `--length long` asks for every relevant detail. Both work with `ask`,
`report` and `chat`, and `answer_language` / `answer_length` in `docsage.toml` set them for
every command, the MCP server included:

```bash
docsage ask "how is the index stored?" --language Portuguese --length short
```

## Chat

`docsage chat` opens an interactive session for questions that build on each other
("which retriever is the default?", then "and how do I switch it?"). Every question
retrieves its own passages, and Claude also gets the earlier questions and answers so
follow-ups make sense. Only the text of old turns is sent, not their passages, and only
the last `chat_history_turns` turns (default 10), so long sessions stay cheap. Answers are
streamed with their sources listed after them. Type `/reset` to start a new conversation
and `/exit` (or Ctrl-D) to leave; `-k` and `--model` work as in `ask`.

## Token usage and cost

Every answer records the tokens Claude spent on it: uncached input, input written to and
read from the prompt cache, and output, plus an estimate of the price in US dollars from
the list prices of the model that actually answered (a fallback model, if the first one
declined). `--usage` on `ask` and `chat` prints it after the sources:

```bash
docsage ask "how is the index stored?" --usage
# Usage: claude-opus-5-5: 4,210 input tokens (3,900 cached), 312 output tokens, ~$0.0083
```

`ask --json` and the MCP `ask_documents` tool always include `usage` and `cost_usd`
(`null` when no passage matched or the model's price is unknown), and `docsage report`
charts the token breakdown under the sources. Prices are estimates from a fixed table;
your bill is the source of truth.

## Output for scripts

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

## Logs

Add `-v`/`--verbose` before the command to log what docsage is doing to stderr,
one `key=value` line per event (documents indexed or skipped, index loads and
saves, retrieval counts, Claude token usage), so stdout stays clean for `--json`:

```bash
docsage --verbose index ./docs
# level=debug logger=docsage.application.services event="indexed document" source=docs/a.md chunks=3
```

## Configuration

Put a `docsage.toml` in the folder you run `docsage` from (or pass `--config path`)
to change the defaults. Every key is optional; command-line flags win over the file.

```toml
index_path = ".docsage/index.json"   # relative paths are resolved from this file's folder
chunk_size = 200                     # words per chunk
chunk_overlap = 40                   # words shared between consecutive chunks
chunker = "window"                   # or "sentence": never cut a sentence in half
model = "claude-opus-5-5"            # model used by `ask`
retriever = "bm25"                   # or "embedding", "hybrid"
embedding_model = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
rerank = false                       # let Claude reorder the best candidates
rerank_candidates = 20               # how many candidates Claude grades
prompt_cache = true                  # cache the passages sent to Claude
chat_history_turns = 10              # earlier turns `chat` sends with each question
answer_language = ""                 # e.g. "Portuguese"; empty: the question's language
answer_length = "medium"             # or "short", "long"
```
