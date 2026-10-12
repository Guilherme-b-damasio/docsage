from docsage.domain.models import DocumentRelation, IndexOverview
from docsage.infrastructure.mermaid import (
    MermaidDashboardRenderer,
    document_labels,
    edge_label,
    relations_diagram,
)


def test_diagram_has_one_node_per_document_and_one_edge_per_relation():
    diagram = relations_diagram(
        [
            DocumentRelation("docs/a.md", "docs/b.md", ("bm25", "ranking", "index")),
            DocumentRelation("docs/a.md", "c.txt", ("install",)),
        ]
    )

    assert diagram == (
        "graph LR\n"
        '  d0["c.txt"]\n'
        '  d1["a.md"]\n'
        '  d2["b.md"]\n'
        '  d1 ===|"bm25, ranking, index"| d2\n'
        '  d1 ---|"install"| d0\n'
    )


def test_diagram_without_relations_says_so():
    assert relations_diagram([]) == 'graph LR\n  empty["No documents share top terms"]\n'


def test_labels_fall_back_to_the_path_when_names_collide():
    labels = document_labels([r"a\notes.md", "b/notes.md", "c/other.md"])

    assert labels == {
        r"a\notes.md": "a/notes.md",
        "b/notes.md": "b/notes.md",
        "c/other.md": "other.md",
    }


def test_edge_label_summarizes_extra_terms():
    relation = DocumentRelation("a", "b", ("one", "two", "three", "four", "five"))

    assert edge_label(relation) == "one, two, three +2"


def test_quotes_and_hashes_are_escaped():
    diagram = relations_diagram([DocumentRelation('say "hi".md', "#tag.md", ('c#',))])

    assert '"say #quot;hi#quot;.md"' in diagram
    assert '"#35;tag.md"' in diagram
    assert '|"c#35;"|' in diagram


def test_renderer_draws_the_overview_relations():
    overview = IndexOverview(
        documents=2,
        chunks=2,
        terms=4,
        vocabulary=3,
        index_bytes=10,
        documents_by_type=(("md", 2),),
        chunk_lengths=(),
        top_terms=(),
        relations=(DocumentRelation("a.md", "b.md", ("alpha",)),),
    )

    assert MermaidDashboardRenderer().render(overview).startswith("graph LR\n")
