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

## What the server offers

### Tools

| Tool               | Arguments                  | What it does                                              |
| ------------------ | -------------------------- | --------------------------------------------------------- |
| `search_documents` | `query`, `top_k`           | ranked passages with citations, no model call             |
| `ask_documents`    | `question`, `top_k`        | a cited answer from Claude (needs `ANTHROPIC_API_KEY`)    |
| `index_path`       | `path`, `force`            | index a file or folder; unchanged files are skipped       |
| `remove_path`      | `path`                     | drop a file or folder from the index (files stay on disk) |
| `index_stats`      | `top`                      | documents, chunks, top terms and index size               |

Relative `path` arguments are resolved from the server's working directory, which the
client chooses, so prefer absolute paths.

### Resources

| Resource                      | Contents                                                       |
| ----------------------------- | -------------------------------------------------------------- |
| `docsage://documents`         | every indexed document: chunk count, pages, sections, chunk ids |
| `docsage://chunks/{chunk_id}` | the full text, position and citation of one chunk              |

### Prompts

| Prompt               | Arguments         | Asks for                                                |
| -------------------- | ----------------- | ------------------------------------------------------- |
| `summarize_document` | `source`          | an overview and key points, citing `[1]`, `[2]`         |
| `compare_documents`  | `first`, `second` | shared topics, agreements, differences (`[A1]`, `[B2]`) |

Pass sources exactly as `docsage://documents` lists them.

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
