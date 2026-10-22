"""Human-readable units shared by the CLI, the MCP server and the visual renderers."""

from __future__ import annotations

from datetime import UTC, datetime

from docsage.domain.models import TokenUsage


def human_size(size: int) -> str:
    """Formats a byte count as ``512 B``, ``1.5 KB`` or ``2.0 MB``."""
    if size < 1024:
        return f"{size} B"
    kilobytes = size / 1024
    if kilobytes < 1024:
        return f"{kilobytes:.1f} KB"
    return f"{kilobytes / 1024:.1f} MB"


def usage_summary(usage: TokenUsage, cost_usd: float | None) -> str:
    """One line such as ``claude-opus-5-5: 1,200 input tokens (900 cached), 85 output tokens,
    ~$0.0035``; the price is left out when it is unknown."""
    cached = usage.cache_read_input_tokens
    parts = [
        f"{usage.total_input_tokens:,} input tokens" + (f" ({cached:,} cached)" if cached else ""),
        f"{usage.output_tokens:,} output tokens",
    ]
    if cost_usd is not None:
        parts.append(f"~${cost_usd:.4f}")
    return f"{usage.model}: {', '.join(parts)}"


def indexed_label(timestamp: str) -> str:
    """An ISO 8601 timestamp as ``2026-10-22 09:30 UTC``; ``unknown`` when it is empty and
    the text unchanged when it cannot be read."""
    if not timestamp:
        return "unknown"
    try:
        moment = datetime.fromisoformat(timestamp)
    except ValueError:
        return timestamp
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%d %H:%M UTC")
