# Using docsage from MCP clients

`docsage mcp` serves your local index over the
[Model Context Protocol](https://modelcontextprotocol.io), so Claude Desktop, Claude Code
or any other MCP client can search your documents and answer questions about them.

## 1. Install and build an index

```bash
pip install "docsage[mcp]"          # or, from a clone: pip install -e ".[mcp,pdf]"
docsage --index ~/notes/.docsage/index.json index ~/notes
docsage --index ~/notes/.docsage/index.json search "anything"   # sanity check
```

Clients usually start the server from a different working directory than your shell,
so always pass an **absolute** `--index` (or `--config` pointing at a `docsage.toml`).
If the client cannot find the `docsage` command, use the full path printed by
`which docsage` (macOS/Linux) or `where docsage` (Windows).

`ask_documents` calls the Claude API. Give the server `ANTHROPIC_API_KEY` in its
environment (see the examples below); every other tool works offline.

## 2. Claude Code

Register the server once with `claude mcp add`. Everything after `--` is the command
Claude Code runs:

```bash
claude mcp add docsage -e ANTHROPIC_API_KEY=sk-ant-... -- \
  docsage --index ~/notes/.docsage/index.json mcp
```

Add `--scope user` to make it available in every project, or `--scope project` to
write it to the project's `.mcp.json` so teammates get it too:

```json
{
  "mcpServers": {
    "docsage": {
      "command": "docsage",
      "args": ["--index", ".docsage/index.json", "mcp"]
    }
  }
}
```

Run `claude mcp list` to check it connects, then `/mcp` inside a session to see its tools.

## 3. Claude Desktop

Open *Settings → Developer → Edit Config*, or edit the file directly:

| OS      | Config file                                                        |
| ------- | ------------------------------------------------------------------ |
| macOS   | `~/Library/Application Support/Claude/claude_desktop_config.json`  |
| Windows | `%APPDATA%\Claude\claude_desktop_config.json`                      |

```json
{
  "mcpServers": {
    "docsage": {
      "command": "/absolute/path/to/docsage",
      "args": ["--index", "/Users/me/notes/.docsage/index.json", "mcp"],
      "env": { "ANTHROPIC_API_KEY": "sk-ant-..." }
    }
  }
}
```

On Windows, escape backslashes in JSON (`"C:\\Users\\me\\notes\\.docsage\\index.json"`).
Restart Claude Desktop after saving; docsage then shows up in the tools menu.

## 4. Streamable HTTP

For clients that connect to a URL instead of starting a process, run the server
yourself:

```bash
docsage --index ~/notes/.docsage/index.json mcp --http            # 127.0.0.1:8765
docsage --index ~/notes/.docsage/index.json mcp --http --port 9000
claude mcp add --transport http docsage http://127.0.0.1:8765/mcp
```

The endpoint is always `/mcp`. The server binds to `127.0.0.1` by default; only pass
`--host 0.0.0.0` on a trusted network, since there is no authentication.

## 5. Keeping the index in sync while serving

`--watch <folder>` (repeatable) makes the server index the folder when it starts and
then follow its files for as long as it runs, like `docsage watch`: new and edited
files are re-indexed and deleted ones are dropped (`--interval` sets how often it
looks, default every second). It works with stdio and `--http`:

```bash
docsage --index ~/notes/.docsage/index.json mcp --watch ~/notes
claude mcp add docsage -- docsage --index ~/notes/.docsage/index.json mcp --watch ~/notes
```

Whenever the watcher changes the index, clients listening on `subscriptions/listen`
receive `notifications/resources/list_changed` and an update for
`docsage://documents`, so they can re-read the document list. Clients on older
protocol versions do not get these notifications; they still see the current index
on their next tool call or resource read. Tool calls that write (`index_path`,
`remove_path`, `index_url`, `remove_url`) and the watcher take turns, so neither
overwrites the other's changes.

## What the server offers

### Tools

| Tool               | Arguments                  | What it does                                              |
| ------------------ | -------------------------- | --------------------------------------------------------- |
| `search_documents` | `query`, `top_k`           | ranked passages with citations, no model call             |
| `ask_documents`    | `question`, `top_k`        | a cited answer from Claude (needs `ANTHROPIC_API_KEY`)    |
| `index_path`       | `path`, `force`            | index a file or folder; unchanged files are skipped       |
| `remove_path`      | `path`                     | drop a file or folder from the index (files stay on disk) |
| `index_url`        | `url`, `force`             | fetch a web page and index its main content               |
| `remove_url`       | `url`                      | drop a web page, and the pages below that URL             |
| `index_stats`      | `top`                      | documents, chunks, top terms and index size               |
| `index_dashboard`  | `top`                      | charts of file types, chunk lengths, top terms and related documents |

Relative `path` arguments are resolved from the server's working directory, which the
client chooses, so prefer absolute paths. `index_url` fetches any http(s) address the
client passes, from the machine the server runs on; keep that in mind before exposing
the HTTP transport beyond your own machine.

### Structured output

Every tool publishes an `outputSchema` and returns two things: readable text for the
model, and `structuredContent` that matches the schema for applications and agents
that want fields instead of prose. The structured shapes are the same as the CLI's
`--json` output:

| Tool               | `structuredContent`                                                     |
| ------------------ | ----------------------------------------------------------------------- |
| `search_documents` | `query`, `results[]` with `rank`, `score`, `matched_terms`, `highlights[]`, `contributions[]` and the full `chunk` |
| `ask_documents`    | `question`, `answer`, `sources[]` ranked like search results            |
| `index_path`       | `documents`, `chunks`, `unchanged`, `skipped[]`, `failed[]`             |
| `remove_path`      | `path`, `documents[]`, `chunks`                                         |
| `index_url`        | same as `index_path`                                                    |
| `remove_url`       | same as `remove_path`                                                   |
| `index_stats`      | `documents`, `chunks`, `terms`, `vocabulary`, `top_terms[]`, `index_bytes` |
| `index_dashboard`  | the `index_stats` fields plus `documents_by_type[]`, `chunk_lengths[]` (`low`, `high`, `chunks`) and `relations[]` (`first`, `second`, `shared_terms[]`) |

Search results carry each chunk's full text in `structuredContent`; the text output
shortens long passages to a preview. Each `highlights[]` entry gives the `start` and
`end` character offsets in `chunk.text` where a query `term` occurs, so a client can
render the passage with the matches marked. Each `contributions[]` entry gives the
share of `score` a query `term` added (BM25), largest first. A failed call returns an error and no structured
content.

### Resources

| Resource                      | Contents                                                       |
| ----------------------------- | -------------------------------------------------------------- |
| `docsage://documents`         | every indexed document: chunk count, pages, sections, chunk ids |
| `docsage://chunks/{chunk_id}` | the full text, position and citation of one chunk              |
| `ui://docsage/dashboard`      | the MCP Apps view of `index_dashboard` (see Visual output)     |
| `ui://docsage/answer-report`  | the MCP Apps view of `ask_documents` (see Visual output)       |
| `ui://docsage/search-results` | the MCP Apps view of `search_documents` (see Visual output)    |
| `ui://docsage/index-stats`    | the MCP Apps view of `index_stats` (see Visual output)         |

### Prompts

| Prompt               | Arguments         | Asks for                                                |
| -------------------- | ----------------- | ------------------------------------------------------- |
| `summarize_document` | `source`          | an overview and key points, citing `[1]`, `[2]`         |
| `compare_documents`  | `first`, `second` | shared topics, agreements, differences (`[A1]`, `[B2]`) |

Pass sources exactly as `docsage://documents` lists them.

### Visual output (MCP Apps)

`search_documents`, `ask_documents`, `index_stats` and `index_dashboard` link an [MCP Apps](https://github.com/modelcontextprotocol/ext-apps)
view through their `_meta.ui.resourceUri`. Hosts that support MCP Apps render that
`ui://` resource (`text/html;profile=mcp-app`) in a sandboxed frame next to the tool
call and show:

- `search_documents`: the ranked passages with their matched terms highlighted and a
  bar chart of each passage's BM25 score, term by term.
- `ask_documents`: the HTML answer report, with every cited passage and its matched
  terms highlighted and a score breakdown chart per source.
- `index_stats`: stat tiles for documents, chunks, distinct terms and index size, and
  a bar chart of the top terms with a table view.
- `index_dashboard`: the HTML index dashboard, with stat tiles and charts of file
  types, chunk lengths and top terms.

The server renders the page and sends it in the tool result's `_meta["docsage/html"]`,
which hosts never add to the model's context; the view swaps it in, follows the host's
light or dark theme and reports its height. Nothing is loaded from the network.
Clicking a passage's citation in the answer report asks the host to open its source
(`ui/open-link`), since the sandboxed view cannot open links itself; the host may ask
the user first.

Hosts without MCP Apps ignore the link and show the text content, which always carries
the ranked passages, the answer with its sources, the stats or the dashboard as text bars, so every tool stays usable
from any client.

## Troubleshooting

- **The server does not start.** Run the exact command from the client config in a
  terminal. `docsage: the MCP server needs: pip install "docsage[mcp]"` means the extra
  is missing from the Python environment that `docsage` runs in.
- **Searches return nothing.** The server is probably reading a different index. Check
  `index_stats`, and make `--index` absolute.
- **`ask_documents` fails.** `ANTHROPIC_API_KEY` is not set in the server's environment;
  clients do not inherit your shell's variables.
- **Need more detail.** Add `--verbose` before `mcp` to log `key=value` events to
  stderr; stdout stays reserved for the protocol. Claude Desktop writes server stderr
  to its `mcp-server-docsage.log` file.
- **Inspect it by hand.** `npx @modelcontextprotocol/inspector docsage --index
  /abs/path/index.json mcp` opens a UI that lists and calls every tool, resource and
  prompt.
