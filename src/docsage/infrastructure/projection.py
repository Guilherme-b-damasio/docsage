"""2D maps of chunk embeddings via principal component analysis (pure Python)."""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from operator import mul

from docsage.domain.models import Chunk, ChunkPoint
from docsage.domain.ports import Embedder

Vector = list[float]


class PcaProjector:
    """Embeds chunks and keeps the two directions along which the vectors vary most.

    Principal components come from power iteration on the centered vectors, so no
    covariance matrix is built and no numeric library is needed. Each axis is scaled
    to ``-1..1``; the sign of each component is fixed so repeated runs give the same map.
    """

    def __init__(self, embedder: Embedder, iterations: int = 50, tolerance: float = 1e-8) -> None:
        self._embedder = embedder
        self._iterations = iterations
        self._tolerance = tolerance

    def project(self, chunks: Sequence[Chunk]) -> list[ChunkPoint]:
        if not chunks:
            return []
        vectors = self._embedder.embed([chunk.text for chunk in chunks])
        centered = _centered(vectors)
        columns = [list(column) for column in zip(*centered, strict=True)]
        components: list[Vector] = []
        for _ in range(2):
            components.append(self._principal_component(centered, columns, components))
        xs = _scaled([_dot(row, components[0]) for row in centered])
        ys = _scaled([_dot(row, components[1]) for row in centered])
        return [
            ChunkPoint(chunk.id, chunk.source, x, y)
            for chunk, x, y in zip(chunks, xs, ys, strict=True)
        ]

    def _principal_component(
        self, rows: list[Vector], columns: list[Vector], found: list[Vector]
    ) -> Vector:
        """The unit direction of largest variance orthogonal to every ``found`` one.

        ``columns`` is ``rows`` transposed, so both products are plain dot products.
        """
        generator = random.Random(len(found))
        vector = _orthogonal([generator.uniform(-1, 1) for _ in columns], found)
        vector = _normalized(vector)
        for _ in range(self._iterations):
            scores = [_dot(row, vector) for row in rows]
            following = _orthogonal([_dot(column, scores) for column in columns], found)
            following = _normalized(following)
            change = sum((a - b) ** 2 for a, b in zip(following, vector, strict=True))
            vector = following
            if change < self._tolerance:
                break
        return _fixed_sign(vector)


def _centered(vectors: Sequence[Sequence[float]]) -> list[Vector]:
    mean = [sum(column) / len(vectors) for column in zip(*vectors, strict=True)]
    return [[value - centre for value, centre in zip(row, mean, strict=True)] for row in vectors]


def _dot(first: Sequence[float], second: Sequence[float]) -> float:
    return float(sum(map(mul, first, second)))


def _orthogonal(vector: Vector, basis: Sequence[Vector]) -> Vector:
    for direction in basis:
        overlap = _dot(vector, direction)
        vector = [value - overlap * axis for value, axis in zip(vector, direction, strict=True)]
    return vector


def _normalized(vector: Vector) -> Vector:
    length = math.sqrt(_dot(vector, vector))
    return [value / length for value in vector] if length else vector


def _fixed_sign(vector: Vector) -> Vector:
    """Flips ``vector`` so its largest component is positive (PCA signs are arbitrary)."""
    largest = max(vector, key=abs, default=0.0)
    return [-value for value in vector] if largest < 0 else vector


def _scaled(values: Sequence[float]) -> list[float]:
    peak = max((abs(value) for value in values), default=0.0)
    return [value / peak if peak > 1e-12 else 0.0 for value in values]
