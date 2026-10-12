"""The HTML view an MCP Apps host embeds next to a tool result.

MCP Apps (extension ``io.modelcontextprotocol/ui``) lets a tool point at a ``ui://``
resource that the host renders in a sandboxed iframe. The view talks to the host with
JSON-RPC over ``postMessage``: it sends ``ui/initialize``, then
``ui/notifications/initialized``, and the host answers with the tool result.

This view is a small shell: the tool renders its visual output on the server with the
regular HTML renderers and puts the complete page in the result's ``_meta`` under
``HTML_META_KEY`` (``_meta`` never reaches the model). The shell swaps that page in,
applies the host's light or dark theme and reports its size. When the page is missing it
shows the result's text content, the same fallback hosts without MCP Apps display.
"""

from __future__ import annotations

import json
from html import escape

from docsage.infrastructure.html_page import page

APP_MIME_TYPE = "text/html;profile=mcp-app"
"""MIME type MCP Apps hosts require for a UI resource."""

HTML_META_KEY = "docsage/html"
"""Key in a tool result's ``_meta`` holding the rendered HTML page."""

PROTOCOL_VERSION = "2026-01-26"

VIEW_CSS = """
#fallback { white-space: pre-wrap; font: 0.9rem/1.5 ui-monospace, Consolas, monospace; }
"""

BRIDGE_JS = """
(() => {
  const META_KEY = __META_KEY__;
  const fallback = document.getElementById("fallback");
  const pending = new Map();
  let nextId = 1;
  let theme = null;

  const send = (message) => window.parent.postMessage({ jsonrpc: "2.0", ...message }, "*");
  const request = (method, params) =>
    new Promise((resolve) => {
      const id = nextId++;
      pending.set(id, resolve);
      send({ id, method, params });
    });
  const applyTheme = (context) => {
    if (context && (context.theme === "light" || context.theme === "dark")) {
      theme = context.theme;
      document.documentElement.dataset.theme = theme;
    }
  };
  const reportSize = () =>
    send({
      method: "ui/notifications/size-changed",
      params: {
        width: document.documentElement.scrollWidth,
        height: document.documentElement.scrollHeight,
      },
    });
  const showPage = (html) => {
    const parsed = new DOMParser().parseFromString(html, "text/html");
    const imported = (nodes) => Array.from(nodes, (node) => document.importNode(node, true));
    document.title = parsed.title;
    document.head.replaceChildren(...imported(parsed.head.childNodes));
    document.body.replaceChildren(...imported(parsed.body.childNodes));
    if (theme) document.documentElement.dataset.theme = theme;
  };
  const showText = (result) => {
    const blocks = (result.content || []).filter((block) => block.type === "text");
    fallback.textContent = blocks.map((block) => block.text).join("\\n\\n") || "No output.";
  };
  const showResult = (result) => {
    const html = result._meta && result._meta[META_KEY];
    if (typeof html === "string") showPage(html);
    else showText(result);
    reportSize();
  };

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const message = event.data;
    if (!message || message.jsonrpc !== "2.0") return;
    if (message.method === undefined) {
      const resolve = pending.get(message.id);
      pending.delete(message.id);
      if (resolve) resolve(message.result || {});
    } else if (message.id !== undefined) {
      send({ id: message.id, result: {} });
    } else if (message.method === "ui/notifications/tool-result") {
      showResult(message.params || {});
    } else if (message.method === "ui/notifications/host-context-changed") {
      applyTheme(message.params);
    } else if (message.method === "ui/notifications/tool-cancelled") {
      fallback.textContent = "The tool call was cancelled.";
    }
  });

  request("ui/initialize", {
    protocolVersion: __PROTOCOL_VERSION__,
    appInfo: { name: "docsage", version: __VERSION__ },
    appCapabilities: {},
  }).then((result) => {
    applyTheme(result.hostContext);
    send({ method: "ui/notifications/initialized", params: {} });
  });
})();
"""


def app_view(title: str, version: str) -> str:
    """A self-contained view titled ``title`` that shows the tool result it receives."""
    script = (
        BRIDGE_JS.replace("__META_KEY__", json.dumps(HTML_META_KEY))
        .replace("__PROTOCOL_VERSION__", json.dumps(PROTOCOL_VERSION))
        .replace("__VERSION__", json.dumps(version))
    )
    body = (
        f"<h1>{escape(title)}</h1>\n"
        '<p id="fallback" class="muted">Waiting for the tool result…</p>\n'
        f"<script>{script}</script>"
    )
    return page(title, body, VIEW_CSS)
