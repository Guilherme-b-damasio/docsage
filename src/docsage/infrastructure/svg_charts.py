"""Tiny inline-SVG chart builders for the HTML dashboard (no JavaScript, no network).

Charts follow the page's CSS tokens (``--bar``, ``--grid``, ``--text``, ``--muted``) so
they switch with light and dark mode. Bars are at most 20px thick, rounded only at the
data end, separated by a 2px gap, and carry a ``<title>`` that browsers show on hover.
"""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

WIDTH = 800
BAR = 20
GAP = 8
RADIUS = 4
CHAR_WIDTH = 7.5
"""Rough width of one 12px label character, used to size the label column."""


def bar_chart(rows: Sequence[tuple[str, int]], label: str) -> str:
    """Horizontal bars, one per ``(name, value)`` row, with the value at each bar's tip."""
    if not rows:
        return ""
    names_width = min(180, max(40, int(max(len(name) for name, _ in rows) * CHAR_WIDTH) + 20))
    values_width = int(len(f"{max(value for _, value in rows):,}") * CHAR_WIDTH) + 12
    track = WIDTH - names_width - values_width
    peak = max(value for _, value in rows) or 1
    height = len(rows) * (BAR + GAP) - GAP
    marks = []
    for index, (name, value) in enumerate(rows):
        top = index * (BAR + GAP)
        length = track * value / peak
        middle = top + BAR / 2
        marks.append(
            f'<g class="mark"><title>{escape(name)}: {value:,}</title>'
            f'<text class="axis" x="{names_width - 12}" y="{middle}" text-anchor="end" '
            f'dominant-baseline="central">{escape(_clip(name, names_width))}</text>'
            f'<path class="bar" d="{_horizontal_bar(names_width, top, length)}"/>'
            f'<text class="value" x="{names_width + length + 6:.1f}" y="{middle}" '
            f'dominant-baseline="central">{value:,}</text></g>'
        )
    return _svg(height, label, "".join(marks))


def column_chart(columns: Sequence[tuple[str, int]], label: str) -> str:
    """Vertical columns over a baseline with each column's name underneath."""
    if not columns:
        return ""
    plot = 180
    peak = max(value for _, value in columns) or 1
    slot = WIDTH / len(columns)
    thickness = min(48.0, slot - 2)
    marks = [f'<line class="grid" x1="0" x2="{WIDTH}" y1="{plot + 20}" y2="{plot + 20}"/>']
    for index, (name, value) in enumerate(columns):
        left = index * slot + (slot - thickness) / 2
        size = plot * value / peak
        top = plot + 20 - size
        centre = left + thickness / 2
        value_label = (
            f'<text class="value" x="{centre:.1f}" y="{top - 6:.1f}" '
            f'text-anchor="middle">{value:,}</text>'
            if value
            else ""
        )
        marks.append(
            f'<g class="mark"><title>{escape(name)}: {value:,}</title>'
            f'<rect class="hit" x="{index * slot:.1f}" y="0" width="{slot:.1f}" '
            f'height="{plot + 20}"/>'
            f'<path class="bar" d="{_vertical_bar(left, plot + 20, thickness, size)}"/>'
            f"{value_label}"
            f'<text class="axis" x="{centre:.1f}" y="{plot + 38}" '
            f'text-anchor="middle">{escape(name)}</text></g>'
        )
    return _svg(plot + 44, label, "".join(marks))


def data_table(headers: tuple[str, str], rows: Sequence[tuple[str, int]]) -> str:
    """The chart's numbers as a collapsible table, so nothing depends on the graphic."""
    body = "".join(
        f"<tr><td>{escape(name)}</td><td>{value:,}</td></tr>" for name, value in rows
    )
    return (
        "<details><summary>Show as table</summary>"
        f"<table><thead><tr><th>{escape(headers[0])}</th><th>{escape(headers[1])}</th>"
        f"</tr></thead><tbody>{body}</tbody></table></details>"
    )


CHART_CSS = """
svg.chart { width: 100%; height: auto; display: block; overflow: visible; }
svg.chart text { font-size: 12px; font-family: inherit; }
svg.chart .axis { fill: var(--muted); }
svg.chart .value { fill: var(--text); font-variant-numeric: tabular-nums; }
svg.chart .bar { fill: var(--bar); }
svg.chart .grid { stroke: var(--grid); stroke-width: 1; }
svg.chart .hit { fill: transparent; }
svg.chart .mark:hover .bar { opacity: 0.8; }
details { margin-top: 12px; font-size: 0.9rem; }
summary { cursor: pointer; color: var(--muted); }
table { border-collapse: collapse; margin-top: 8px; }
th, td { text-align: left; padding: 2px 16px 2px 0; border-bottom: 1px solid var(--border); }
td:last-child { font-variant-numeric: tabular-nums; }
"""


def _svg(height: float, label: str, content: str) -> str:
    return (
        f'<svg class="chart" viewBox="0 0 {WIDTH} {height:g}" role="img" '
        f'aria-label="{escape(label)}">{content}</svg>'
    )


def _horizontal_bar(left: float, top: float, length: float) -> str:
    """A bar growing right from ``left``: square at the baseline, rounded at its tip."""
    radius = min(RADIUS, length / 2)
    right = left + length
    return (
        f"M{left:.1f},{top:.1f}H{right - radius:.1f}"
        f"A{radius:.1f},{radius:.1f} 0 0 1 {right:.1f},{top + radius:.1f}"
        f"V{top + BAR - radius:.1f}"
        f"A{radius:.1f},{radius:.1f} 0 0 1 {right - radius:.1f},{top + BAR:.1f}"
        f"H{left:.1f}Z"
    )


def _vertical_bar(left: float, baseline: float, thickness: float, size: float) -> str:
    """A column growing up from ``baseline``: square at the bottom, rounded at the top."""
    radius = min(RADIUS, size / 2, thickness / 2)
    top = baseline - size
    right = left + thickness
    return (
        f"M{left:.1f},{baseline:.1f}V{top + radius:.1f}"
        f"A{radius:.1f},{radius:.1f} 0 0 1 {left + radius:.1f},{top:.1f}"
        f"H{right - radius:.1f}"
        f"A{radius:.1f},{radius:.1f} 0 0 1 {right:.1f},{top + radius:.1f}"
        f"V{baseline:.1f}Z"
    )


def _clip(name: str, width: int) -> str:
    limit = max(4, int((width - 12) / CHAR_WIDTH))
    return name if len(name) <= limit else name[: limit - 1] + "…"
