"""Self-contained HTML page shell shared by the visual renderers.

Every page inlines its CSS, so a report opens offline and can be attached or shared as a
single file. Colors are CSS custom properties redefined under ``prefers-color-scheme: dark``.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

from docsage.domain.models import Highlight

BASE_CSS = """
:root {
  --bg: #fbfbfa; --surface: #ffffff; --text: #1f2328; --muted: #59636e;
  --border: #d8dee4; --accent: #0b6bcb; --mark: #fff1a8; --mark-text: #1f2328;
  --bar: #0b6bcb; --bar-alt: #8a63d2;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0f1216; --surface: #171b21; --text: #e6e8eb; --muted: #9aa4b0;
    --border: #2d333b; --accent: #58a6ff; --mark: #6b5a12; --mark-text: #fff8d6;
    --bar: #58a6ff; --bar-alt: #b392f0;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; background: var(--bg); color: var(--text);
  font: 16px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
}
main { max-width: 860px; margin: 0 auto; padding: 32px 16px 64px; }
h1 { font-size: 1.6rem; line-height: 1.3; margin: 0 0 4px; }
h2 { font-size: 1.1rem; margin: 32px 0 12px; }
a { color: var(--accent); }
.muted { color: var(--muted); font-size: 0.9rem; }
.card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 16px; margin: 0 0 12px;
}
mark { background: var(--mark); color: var(--mark-text); border-radius: 3px; padding: 0 2px; }
""".strip()


def page(title: str, body: str, extra_css: str = "") -> str:
    """Wraps ``body`` (already escaped HTML) in a complete document titled ``title``."""
    css = f"{BASE_CSS}\n{extra_css.strip()}" if extra_css else BASE_CSS
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        '<meta name="color-scheme" content="light dark">\n'
        f"<title>{escape(title)}</title>\n<style>\n{css}\n</style>\n</head>\n"
        f"<body>\n<main>\n{body}\n</main>\n</body>\n</html>\n"
    )


def highlighted(text: str, highlights: Sequence[Highlight]) -> str:
    """Escapes ``text`` and wraps each highlighted span in ``<mark>``.

    Spans are expected in text order without overlaps, as ``Highlighter`` returns them;
    any span that overlaps the previous one is skipped rather than producing broken markup.
    """
    parts: list[str] = []
    cursor = 0
    for highlight in sorted(highlights, key=lambda item: item.start):
        if highlight.start < cursor or highlight.end > len(text):
            continue
        parts.append(escape(text[cursor : highlight.start]))
        parts.append(
            f'<mark title="{escape(highlight.term)}">'
            f"{escape(text[highlight.start : highlight.end])}</mark>"
        )
        cursor = highlight.end
    parts.append(escape(text[cursor:]))
    return "".join(parts)
