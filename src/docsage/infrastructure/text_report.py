"""Plain-text fallback for clients that cannot show HTML reports."""

from __future__ import annotations

from collections.abc import Sequence

from docsage.domain.models import Answer, Highlight


class TextAnswerRenderer:
    """The answer followed by its numbered sources, with matched terms in ``**bold**``."""

    def render(self, answer: Answer) -> str:
        lines = [answer.question, "=" * len(answer.question), "", answer.text.strip()]
        if answer.sources:
            lines += ["", "Sources:"]
        for rank, result in enumerate(answer.sources, start=1):
            lines += [
                "",
                f"[{rank}] {result.chunk.citation} (score {result.score:.2f})",
                _indent(emphasized(result.chunk.text, result.highlights)),
            ]
        return "\n".join(lines) + "\n"


def emphasized(text: str, highlights: Sequence[Highlight]) -> str:
    """Wraps each highlighted span in ``**``, skipping overlapping or out-of-range spans."""
    parts: list[str] = []
    cursor = 0
    for highlight in sorted(highlights, key=lambda item: item.start):
        if highlight.start < cursor or highlight.end > len(text):
            continue
        parts += [text[cursor : highlight.start], f"**{text[highlight.start : highlight.end]}**"]
        cursor = highlight.end
    parts.append(text[cursor:])
    return "".join(parts)


def _indent(text: str) -> str:
    return "\n".join(f"    {line}" if line else "" for line in text.strip().splitlines())
