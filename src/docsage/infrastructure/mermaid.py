"""Mermaid diagrams of the index, for Markdown files, GitHub and other Mermaid viewers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from pathlib import PureWindowsPath

from docsage.domain.models import DocumentRelation, IndexOverview

EDGE_TERMS = 3
"""Shared terms written on an edge; the rest are summarized as ``+N``."""

STRONG_RELATION = 3
"""Relations sharing at least this many terms are drawn with a thick line."""


def relations_diagram(relations: Sequence[DocumentRelation]) -> str:
    """A ``graph LR`` with one node per related document and one edge per relation.

    Nodes are labeled with the file name, or the full path when two related documents
    share a name. Edges list the shared terms; strong relations get a thick line.
    """
    sources = sorted({source for item in relations for source in (item.first, item.second)})
    ids = {source: f"d{index}" for index, source in enumerate(sources)}
    labels = document_labels(sources)
    lines = ["graph LR"]
    if not relations:
        lines.append('  empty["No documents share top terms"]')
    lines += [f'  {ids[source]}["{_escape(labels[source])}"]' for source in sources]
    for relation in relations:
        link = "===" if relation.strength >= STRONG_RELATION else "---"
        lines.append(
            f'  {ids[relation.first]} {link}|"{_escape(edge_label(relation))}"| '
            f"{ids[relation.second]}"
        )
    return "\n".join(lines) + "\n"


def document_labels(sources: Sequence[str]) -> dict[str, str]:
    """Short names for ``sources``: the file name unless two sources share it."""
    names = {source: PureWindowsPath(source).name for source in sources}
    taken = Counter(names.values())
    return {
        source: name if taken[name] == 1 else source.replace("\\", "/")
        for source, name in names.items()
    }


def edge_label(relation: DocumentRelation) -> str:
    shown = ", ".join(relation.shared_terms[:EDGE_TERMS])
    hidden = relation.strength - EDGE_TERMS
    return f"{shown} +{hidden}" if hidden > 0 else shown


def _escape(text: str) -> str:
    return text.replace("#", "#35;").replace('"', "#quot;")


class MermaidDashboardRenderer:
    """The dashboard's document relationships as Mermaid source, ready to paste into
    a Markdown file."""

    def render(self, overview: IndexOverview) -> str:
        return relations_diagram(overview.relations)
