import pytest

from docsage.domain.models import Chunk
from docsage.infrastructure.projection import PcaProjector


class TableEmbedder:
    """Returns a fixed vector per text."""

    def __init__(self, vectors: dict[str, list[float]]) -> None:
        self._vectors = vectors
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [self._vectors[text] for text in texts]


def _chunks(*texts: str) -> list[Chunk]:
    return [Chunk(id=t, source=f"{t}.md", text=t, position=0) for t in texts]


def test_first_axis_follows_the_direction_of_largest_spread():
    embedder = TableEmbedder(
        {
            "a": [-10.0, 0.0, 1.0],
            "b": [10.0, 0.0, 1.0],
            "c": [0.0, 1.0, 1.0],
            "d": [0.0, -1.0, 1.0],
        }
    )

    points = PcaProjector(embedder).project(_chunks("a", "b", "c", "d"))

    by_id = {point.chunk_id: point for point in points}
    assert sorted(abs(by_id[i].x) for i in "ab") == pytest.approx([1.0, 1.0])
    assert by_id["c"].x == pytest.approx(0.0, abs=1e-3)
    assert sorted(abs(by_id[i].y) for i in "cd") == pytest.approx([1.0, 1.0])
    assert by_id["a"].y == pytest.approx(0.0, abs=1e-3)


def test_points_keep_chunk_order_and_sources_and_stay_in_range():
    vectors = {str(n): [float(n), float(n * n % 7), float(n % 3)] for n in range(12)}
    chunks = _chunks(*vectors)

    points = PcaProjector(TableEmbedder(vectors)).project(chunks)

    assert [(p.chunk_id, p.source) for p in points] == [(c.id, c.source) for c in chunks]
    assert all(-1.0 <= value <= 1.0 for p in points for value in (p.x, p.y))


def test_projection_is_deterministic():
    vectors = {str(n): [float(n % 4), float(n % 5), float(n)] for n in range(9)}
    chunks = _chunks(*vectors)

    first = PcaProjector(TableEmbedder(vectors)).project(chunks)
    second = PcaProjector(TableEmbedder(vectors)).project(chunks)

    assert first == second


def test_identical_vectors_collapse_to_the_origin():
    embedder = TableEmbedder({"a": [1.0, 2.0], "b": [1.0, 2.0]})

    points = PcaProjector(embedder).project(_chunks("a", "b"))

    assert [(p.x, p.y) for p in points] == [(0.0, 0.0), (0.0, 0.0)]


def test_no_chunks_embeds_nothing():
    embedder = TableEmbedder({})

    assert PcaProjector(embedder).project([]) == []
    assert embedder.calls == 0
