"""Plain-text helpers shared by the CLI and the MCP server."""

from __future__ import annotations


def human_size(size: int) -> str:
    """Formats a byte count as ``512 B``, ``1.5 KB`` or ``2.0 MB``."""
    if size < 1024:
        return f"{size} B"
    kilobytes = size / 1024
    if kilobytes < 1024:
        return f"{kilobytes:.1f} KB"
    return f"{kilobytes / 1024:.1f} MB"
