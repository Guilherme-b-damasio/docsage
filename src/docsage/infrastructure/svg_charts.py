"""Tiny inline-SVG chart builders for the HTML dashboard (no JavaScript, no network).

Charts follow the page's CSS tokens (``--bar``, ``--grid``, ``--text``, ``--muted``) so
they switch with light and dark mode. Bars are at most 20px thick, rounded only at the
data end, separated by a 2px gap, and carry a ``<title>`` that browsers show on hover.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from html import escape

WIDTH = 800
BAR = 20
GAP = 8
RADIUS = 4
CHAR_WIDTH = 7.5
"""Rough width of one 12px label character, used to size the label column."""

ValueFormat = Callable[[float], str]
thousands: ValueFormat = "{:,}".format
"""Default value label: ``1,234`` for counts."""
percent: ValueFormat = "{:.0%}".format
"""Value label for shares: ``0.5`` reads ``50%``."""


def bar_chart(
    rows: Sequence[tuple[str, float]],
    label: str,
    value_format: ValueFormat = thousands,
    full_scale: float | None = None,
) -> str:
    """Horizontal bars, one per ``(name, value)`` row, with the value at each bar's tip.

    Bars are scaled so ``full_scale`` (default: the largest value) fills the track, e.g.
    ``1.0`` for shares so that 50% always reaches halfway.
    """
    if not rows:
        return ""
    names_width = min(180, max(40, int(max(len(name) for name, _ in rows) * CHAR_WIDTH) + 20))
    widest = max(len(value_format(value)) for _, value in rows)
    values_width = int(widest * CHAR_WIDTH) + 12
    track = WIDTH - names_width - values_width
    peak = full_scale or max(value for _, value in rows) or 1
    height = len(rows) * (BAR + GAP) - GAP
    marks = []
    for index, (name, value) in enumerate(rows):
        top = index * (BAR + GAP)
        length = track * value / peak
        middle = top + BAR / 2
        marks.append(
            f'<g class="mark"><title>{escape(name)}: {value_format(value)}</title>'
            f'<text class="axis" x="{names_width - 12}" y="{middle}" text-anchor="end" '
            f'dominant-baseline="central">{escape(_clip(name, names_width))}</text>'
            f'<path class="bar" d="{_horizontal_bar(names_width, top, length)}"/>'
            f'<text class="value" x="{names_width + length + 6:.1f}" y="{middle}" '
            f'dominant-baseline="central">{value_format(value)}</text></g>'
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


def network_chart(
    nodes: Sequence[str], edges: Sequence[tuple[int, int, int, str]], label: str
) -> str:
    """Nodes on a circle joined by edges ``(first, second, weight, tooltip)``.

    ``first`` and ``second`` index into ``nodes``; heavier edges are drawn thicker.
    Each node's name sits outside the circle so names never cross the edges.
    """
    if not nodes:
        return ""
    radius = 140
    centre_x, centre_y = WIDTH / 2, radius + 24
    points = [
        (
            centre_x + radius * math.cos(math.pi + 2 * math.pi * index / len(nodes)),
            centre_y + radius * math.sin(math.pi + 2 * math.pi * index / len(nodes)),
        )
        for index in range(len(nodes))
    ]
    peak = max((weight for *_, weight, _ in edges), default=1) or 1
    marks = []
    for first, second, weight, tooltip in edges:
        (x1, y1), (x2, y2) = points[first], points[second]
        marks.append(
            f'<g class="mark"><title>{escape(tooltip)}</title>'
            f'<line class="edge" x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke-width="{1.5 + 4.5 * weight / peak:.1f}"/></g>'
        )
    for name, (x, y) in zip(nodes, points, strict=True):
        dx, dy = (x - centre_x) / radius, (y - centre_y) / radius
        anchor = "start" if dx > 0.3 else "end" if dx < -0.3 else "middle"
        marks.append(
            f'<g class="mark"><title>{escape(name)}</title>'
            f'<circle class="node" cx="{x:.1f}" cy="{y:.1f}" r="6"/>'
            f'<text class="value" x="{x + 12 * dx:.1f}" y="{y + 14 * dy:.1f}" '
            f'text-anchor="{anchor}" dominant-baseline="central">'
            f"{escape(_clip(name, 200))}</text></g>"
        )
    return _svg(2 * centre_y, label, "".join(marks))


SERIES = 8
"""Categorical colors available; further groups share the neutral "other" color."""


def scatter_chart(
    points: Sequence[tuple[float, float, int, str]], label: str, height: int = 360
) -> str:
    """Dots ``(x, y, series, tooltip)`` with x and y in ``-1..1``.

    ``series`` picks the categorical color ``0..SERIES-1``; anything else is drawn in
    the neutral "other" color. Each dot has a surface ring so overlapping dots stay
    distinct, and a larger transparent hit area for its tooltip.
    """
    if not points:
        return ""
    pad = 16
    half_width, half_height = (WIDTH - 2 * pad) / 2, (height - 2 * pad) / 2
    marks = [
        f'<line class="grid" x1="{pad}" y1="{height / 2:g}" x2="{WIDTH - pad}" '
        f'y2="{height / 2:g}"/>'
        f'<line class="grid" x1="{WIDTH / 2:g}" y1="{pad}" x2="{WIDTH / 2:g}" '
        f'y2="{height - pad}"/>'
    ]
    for x, y, series, tooltip in points:
        cx = WIDTH / 2 + x * half_width
        cy = height / 2 - y * half_height
        colour = _series_class(series)
        marks.append(
            f'<g class="mark"><title>{escape(tooltip)}</title>'
            f'<circle class="hit" cx="{cx:.1f}" cy="{cy:.1f}" r="9"/>'
            f'<circle class="dot {colour}" cx="{cx:.1f}" cy="{cy:.1f}" r="5"/></g>'
        )
    return _svg(height, label, "".join(marks))


def legend(names: Sequence[str]) -> str:
    """Swatch-and-name list for ``scatter_chart`` series, in series order."""
    items = "".join(
        f'<li><span class="swatch {_series_class(index)}"></span>{escape(name)}</li>'
        for index, name in enumerate(names)
    )
    return f'<ul class="legend">{items}</ul>'


def _series_class(index: int) -> str:
    return f"series-{index + 1}" if 0 <= index < SERIES else "series-other"


def text_table(headers: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    """A collapsible table of already formatted cells, for charts with several columns."""
    head = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    return (
        "<details><summary>Show as table</summary>"
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></details>"
    )


def data_table(
    headers: tuple[str, str],
    rows: Sequence[tuple[str, float]],
    value_format: ValueFormat = thousands,
) -> str:
    """The chart's numbers as a collapsible table, so nothing depends on the graphic."""
    body = "".join(
        f"<tr><td>{escape(name)}</td><td>{value_format(value)}</td></tr>" for name, value in rows
    )
    return (
        "<details><summary>Show as table</summary>"
        f"<table><thead><tr><th>{escape(headers[0])}</th><th>{escape(headers[1])}</th>"
        f"</tr></thead><tbody>{body}</tbody></table></details>"
    )


LIGHT_SERIES = """
--series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a; --series-4: #eda100;
--series-5: #e87ba4; --series-6: #008300; --series-7: #4a3aa7; --series-8: #e34948;
--series-other: #8c959f;
""".strip()

DARK_SERIES = """
--series-1: #3987e5; --series-2: #d95926; --series-3: #199e70; --series-4: #c98500;
--series-5: #d55181; --series-6: #008300; --series-7: #9085e9; --series-8: #e66767;
--series-other: #6e7781;
""".strip()

SERIES_CSS = "\n".join(
    [
        f":root {{ {LIGHT_SERIES} }}",
        "@media (prefers-color-scheme: dark) {",
        f'  :root:not([data-theme="light"]) {{ {DARK_SERIES} }}',
        "}",
        f':root[data-theme="dark"] {{ {DARK_SERIES} }}',
        *(f".series-{n} {{ --series: var(--series-{n}); }}" for n in range(1, SERIES + 1)),
        ".series-other { --series: var(--series-other); }",
    ]
)
"""Categorical palette validated for both themes (light and dark steps of the same hues)."""

CHART_CSS = SERIES_CSS + """
svg.chart { width: 100%; height: auto; display: block; overflow: visible; }
svg.chart text { font-size: 12px; font-family: inherit; }
svg.chart .axis { fill: var(--muted); }
svg.chart .value { fill: var(--text); font-variant-numeric: tabular-nums; }
svg.chart .bar { fill: var(--bar); }
svg.chart .grid { stroke: var(--grid); stroke-width: 1; }
svg.chart .hit { fill: transparent; }
svg.chart .mark:hover .bar { opacity: 0.8; }
svg.chart .edge { stroke: var(--bar); stroke-linecap: round; opacity: 0.45; }
svg.chart .mark:hover .edge { opacity: 1; }
svg.chart .node { fill: var(--surface); stroke: var(--bar); stroke-width: 2; }
svg.chart .dot { fill: var(--series); stroke: var(--surface); stroke-width: 2; }
svg.chart .mark:hover .dot { stroke: var(--text); }
.legend { list-style: none; padding: 0; margin: 8px 0 0; display: flex; flex-wrap: wrap; }
.legend li { margin: 0 16px 4px 0; font-size: 0.9rem; display: flex; align-items: center; }
.legend .swatch {
  width: 10px; height: 10px; border-radius: 50%; margin-right: 6px; background: var(--series);
}
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
