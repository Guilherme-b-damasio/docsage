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
through the host (``tools/call``) and swaps in its result, and one built with a
``SliderControl`` a slider that calls a tool with the number it is left on; both need a
host that can proxy tool calls (``hostCapabilities.serverTools``).
When the page is missing it shows the result's text content, the same fallback hosts
without MCP Apps display.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
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
form.refine { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; margin: 24px 0 0; }
form.refine label { font-size: 0.9rem; color: var(--muted); }
form.refine input[type="range"] { flex: 1 1 200px; min-width: 0; accent-color: var(--accent); }
form.refine input:disabled { opacity: 0.6; cursor: progress; }
form.refine output { font-variant-numeric: tabular-nums; min-width: 3ch; }
form.refine .status { flex-basis: 100%; margin: 0; }
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


@dataclass(frozen=True)
class SliderControl:
    """A slider under the view's page that calls ``tool`` with the chosen number.

    Moving it re-runs the tool with ``argument`` set to the number, so the view's charts
    are redrawn by the server; the slider keeps the number it is left on.
    """

    tool: str
    argument: str
    label: str
    """Text next to the slider, e.g. "Top terms"."""
    minimum: int
    maximum: int
    value: int
    """Where the slider starts, i.e. the argument the tool was first called with."""
    step: int = 1

    def __post_init__(self) -> None:
        if self.minimum >= self.maximum:
            raise ValueError("minimum must be below maximum")
        if not self.minimum <= self.value <= self.maximum:
            raise ValueError("value must be between minimum and maximum")
        if self.step < 1:
            raise ValueError("step must be at least 1")


BRIDGE_JS = """
(() => {
  const META_KEY = __META_KEY__;
  const FOLLOW_UP = __FOLLOW_UP__;
  const SLIDER = __SLIDER__;
  const VIEW_CSS = __VIEW_CSS__;
  const fallback = document.getElementById("fallback");
  const pending = new Map();
  let nextId = 1;
  let theme = null;
  let canCallTools = false;
  let sliderValue = SLIDER ? SLIDER.value : 0;

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
    if (SLIDER && canCallTools) document.body.append(sliderForm());
  };
  const textOf = (result) =>
    (result.content || [])
      .filter((block) => block.type === "text")
      .map((block) => block.text)
      .join("\\n\\n");
  // Asks the host to run a tool again; the result replaces the page the view shows.
  const callTool = (name, args) =>
    request("tools/call", { name, arguments: args }).then((result) => {
      if (result.isError) throw new Error(textOf(result) || "The tool call failed.");
      return result;
    });
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
      callTool(FOLLOW_UP.tool, { [FOLLOW_UP.argument]: text })
        .then((result) => {
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
  // Re-runs the tool with the number the slider is left on and swaps in its charts.
  const sliderForm = () => {
    const form = document.createElement("form");
    form.className = "refine";
    const input = document.createElement("input");
    input.type = "range";
    input.id = "refine-value";
    input.min = SLIDER.minimum;
    input.max = SLIDER.maximum;
    input.step = SLIDER.step;
    input.value = sliderValue;
    const label = document.createElement("label");
    label.setAttribute("for", input.id);
    label.textContent = SLIDER.label;
    const output = document.createElement("output");
    output.setAttribute("for", input.id);
    output.textContent = input.value;
    const status = document.createElement("p");
    status.className = "status muted";
    status.setAttribute("role", "status");
    form.append(label, input, output, status);
    form.addEventListener("submit", (event) => event.preventDefault());
    input.addEventListener("input", () => {
      output.textContent = input.value;
    });
    input.addEventListener("change", () => {
      const chosen = Number(input.value);
      input.disabled = true;
      status.textContent = "Waiting for the tool result…";
      callTool(SLIDER.tool, { [SLIDER.argument]: chosen })
        .then((result) => {
          sliderValue = chosen;
          showResult(result);
        })
        .catch((error) => {
          input.disabled = false;
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


def app_view(
    title: str,
    version: str,
    follow_up: FollowUp | None = None,
    slider: SliderControl | None = None,
) -> str:
    """A self-contained view titled ``title`` that shows the tool result it receives.

    With ``follow_up`` the view lets the user call that tool again with typed text, and
    with ``slider`` with a number chosen on a slider; both need a host that proxies tool
    calls.
    """
    form = None if follow_up is None else asdict(follow_up)
    script = (
        BRIDGE_JS.replace("__META_KEY__", json.dumps(HTML_META_KEY))
        .replace("__FOLLOW_UP__", json.dumps(form))
        .replace("__SLIDER__", json.dumps(None if slider is None else asdict(slider)))
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
