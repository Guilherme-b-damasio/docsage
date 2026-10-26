"""Plain-text fallback for a comparison of two answers, one after the other."""

from __future__ import annotations

from docsage.domain.models import AnswerComparison, ComparedAnswer
from docsage.infrastructure.units import plural, usage_summary


class TextComparisonRenderer:
    """The overlap first, then each answer under its settings with its cited passages;
    a passage the other side also retrieved ends in ``(in both)``."""

    def render(self, comparison: AnswerComparison) -> str:
        shared = comparison.shared_chunks()
        lines = [
            comparison.question,
            "=" * len(comparison.question),
            "",
            f"{plural(len(shared), 'passage')} in both answers "
            f"({round(comparison.overlap() * 100)}% overlap)",
        ]
        for side in (comparison.left, comparison.right):
            lines += ["", *_side_lines(side, shared)]
        return "\n".join(lines) + "\n"


def _side_lines(side: ComparedAnswer, shared: frozenset[str]) -> list[str]:
    answer = side.answer
    lines = [side.label, "-" * len(side.label), "", answer.text.strip()]
    if answer.sources:
        lines.append("")
    for rank, result in enumerate(answer.sources, start=1):
        both = " (in both)" if result.chunk.id in shared else ""
        lines.append(f"[{rank}] {result.chunk.citation} (score {result.score:.2f}){both}")
    if answer.usage is not None:
        lines += ["", f"Usage: {usage_summary(answer.usage, answer.cost_usd)}"]
    return lines
