"""The HTML view an MCP Apps host embeds next to a tool result.

MCP Apps (extension ``io.modelcontextprotocol/ui``) lets a tool point at a ``ui://``
resource that the host renders in a sandboxed iframe. The view talks to the host with
JSON-RPC over ``postMessage``: it sends ``ui/initialize``, then
``ui/notifications/initialized``, and the host answers with the tool result.

This view is a small shell: the tool renders its visual output on the server with the
regular HTML renderers and puts the complete page in the result's ``_meta`` under
``HTML_META_KEY`` (``_meta`` never reaches the model). The shell swaps that page in,
applies the host's light or dark theme and reports its size. Links to sources go
through the host (``ui/open-link``), since the sandboxed view cannot open them itself.
A view built with a ``FollowUp`` also shows a form under the page that calls a tool again
through the host (``tools/call``) and swaps in its result, when the host can proxy tool
calls (``hostCapabilities.serverTools``).
When the page is missing it shows the result's text content, the same fallback hosts
without MCP Apps display.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape

from docsage.infrastructure.html_page import page

APP_MIME_TYPE = "text/html;profile=mcp-app"
"""MIME type MCP Apps hosts require for a UI resource."""

HTML_META_KEY = "docsage/html"
"""Key in a tool result's ``_meta`` holding the rendered HTML page."""

PROTOCOL_VERSION = "2026-01-26"

VIEW_CSS = """
#fallback { white-space: pre-wrap; font: 0.9rem/1.5 ui-monospace, Consolas, monospace; }
form.follow-up { display: flex; gap: 8px; flex-wrap: wrap; margin: 24px 0 0; }
form.follow-up input {
  flex: 1 1 260px; min-width: 0; padding: 8px 12px; font: inherit; color: var(--text);
  background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
}
form.follow-up button {
  padding: 8px 14px; font: inherit; border-radius: 6px; cursor: pointer;
  border: 1px solid var(--accent); background: var(--accent); color: #fff;
}
form.follow-up button:disabled { opacity: 0.6; cursor: progress; }
form.follow-up .status { flex-basis: 100%; margin: 0; }
"""


@dataclass(frozen=True)
class FollowUp:
    """A form under the view's page that calls ``tool`` with the typed text as ``argument``."""

    tool: str
    argument: str
    label: str
    """Placeholder of the text field, e.g. "Ask a follow-up question"."""
    action: str = "Send"
    """Text of the submit button."""

BRIDGE_JS = """
(() => {
  const META_KEY = __META_KEY__;
  const FOLLOW_UP = __FOLLOW_UP__;
  const VIEW_CSS = __VIEW_CSS__;
  const fallback = document.getElementById("fallback");
  const pending = new Map();
  let nextId = 1;
  let theme = null;
  let canCallTools = false;

  const send = (message) => window.parent.postMessage({ jsonrpc: "2.0", ...message }, "*");
  const request = (method, params) =>
    new Promise((resolve, reject) => {
      const id = nextId++;
      pending.set(id, { resolve, reject });
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
    const style = document.createElement("style");
    style.textContent = VIEW_CSS;
    document.head.append(style);
    if (theme) document.documentElement.dataset.theme = theme;
    if (FOLLOW_UP && canCallTools) document.body.append(followUpForm());
  };
  const textOf = (result) =>
    (result.content || [])
      .filter((block) => block.type === "text")
      .map((block) => block.text)
      .join("\\n\\n");
  // Calls the follow-up tool through the host and shows its result in place of the page.
  const followUpForm = () => {
    const form = document.createElement("form");
    form.className = "follow-up";
    const input = document.createElement("input");
    input.type = "text";
    input.required = true;
    input.placeholder = FOLLOW_UP.label;
    input.setAttribute("aria-label", FOLLOW_UP.label);
    const button = document.createElement("button");
    button.type = "submit";
    button.textContent = FOLLOW_UP.action;
    const status = document.createElement("p");
    status.className = "status muted";
    status.setAttribute("role", "status");
    form.append(input, button, status);
    form.addEventListener("submit", (event) => {
      event.preventDefault();
      const text = input.value.trim();
      if (!text) return;
      button.disabled = true;
      status.textContent = "Waiting for the tool result…";
      request("tools/call", { name: FOLLOW_UP.tool, arguments: { [FOLLOW_UP.argument]: text } })
        .then((result) => {
          if (result.isError) throw new Error(textOf(result) || "The tool call failed.");
          showResult(result);
          window.scrollTo(0, 0);
        })
        .catch((error) => {
          button.disabled = false;
          status.textContent = error.message || "The tool call failed.";
          reportSize();
        });
    });
    return form;
  };
  const showText = (result) => {
    if (!fallback.isConnected) document.body.replaceChildren(fallback);
    fallback.textContent = textOf(result) || "No output.";
  };
  const showResult = (result) => {
    const html = result._meta && result._meta[META_KEY];
    if (typeof html === "string") showPage(html);
    else showText(result);
    reportSize();
  };

  // The view's sandbox cannot navigate or open windows: the host opens links for it.
  document.addEventListener("click", (event) => {
    const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
    if (!link || link.getAttribute("href").startsWith("#")) return;
    event.preventDefault();
    request("ui/open-link", { url: link.href }).catch(() => {});
  });

  window.addEventListener("message", (event) => {
    if (event.source !== window.parent) return;
    const message = event.data;
    if (!message || message.jsonrpc !== "2.0") return;
    if (message.method === undefined) {
      const call = pending.get(message.id);
      pending.delete(message.id);
      if (!call) return;
      if (message.error) call.reject(new Error(message.error.message || "Request failed."));
      else call.resolve(message.result || {});
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
    canCallTools = Boolean(result.hostCapabilities && result.hostCapabilities.serverTools);
    send({ method: "ui/notifications/initialized", params: {} });
  });
})();
"""


def app_view(title: str, version: str, follow_up: FollowUp | None = None) -> str:
    """A self-contained view titled ``title`` that shows the tool result it receives.

    With ``follow_up``, the view also lets the user call that tool again from the page.
    """
    form = (
        None
        if follow_up is None
        else {
            "tool": follow_up.tool,
            "argument": follow_up.argument,
            "label": follow_up.label,
            "action": follow_up.action,
        }
    )
    script = (
        BRIDGE_JS.replace("__META_KEY__", json.dumps(HTML_META_KEY))
        .replace("__FOLLOW_UP__", json.dumps(form))
        .replace("__VIEW_CSS__", json.dumps(VIEW_CSS))
        .replace("__PROTOCOL_VERSION__", json.dumps(PROTOCOL_VERSION))
        .replace("__VERSION__", json.dumps(version))
    )
    body = (
        f"<h1>{escape(title)}</h1>\n"
        '<p id="fallback" class="muted">Waiting for the tool result…</p>\n'
        f"<script>{script}</script>"
    )
    return page(title, body, VIEW_CSS)
