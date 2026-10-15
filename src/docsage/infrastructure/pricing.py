"""Estimates what an answer cost from the tokens it consumed and per-model prices."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from docsage.domain.models import TokenUsage

CACHE_WRITE_MULTIPLIER = 1.25
"""Writing to the 5-minute prompt cache costs this much more than plain input."""


@dataclass(frozen=True)
class ModelPrice:
    """US dollars per million tokens."""

    input: float
    output: float
    cache_read: float

    @property
    def cache_write(self) -> float:
        return self.input * CACHE_WRITE_MULTIPLIER


CLAUDE_PRICES: dict[str, ModelPrice] = {
    "claude-fable-5-1": ModelPrice(input=10.00, output=50.00, cache_read=0.25),
    "claude-opus-5-5": ModelPrice(input=4.00, output=20.00, cache_read=0.20),
    "claude-opus-5": ModelPrice(input=5.00, output=25.00, cache_read=0.50),
    "claude-opus-4-8": ModelPrice(input=5.00, output=25.00, cache_read=0.50),
    "claude-sonnet-5-5": ModelPrice(input=2.00, output=10.00, cache_read=0.20),
    "claude-sonnet-5": ModelPrice(input=2.00, output=10.00, cache_read=0.20),
    "claude-haiku-5-5": ModelPrice(input=0.10, output=0.50, cache_read=0.01),
}
"""First-party Claude API list prices for the models docsage is likely to run on."""

PER_TOKEN = 1 / 1_000_000


class PriceTable:
    """Prices usage with a fixed table; unknown models are not guessed at."""

    def __init__(self, prices: Mapping[str, ModelPrice] | None = None) -> None:
        self._prices = dict(CLAUDE_PRICES if prices is None else prices)

    def estimate(self, usage: TokenUsage) -> float | None:
        price = self._price(usage.model)
        if price is None:
            return None
        return PER_TOKEN * (
            usage.input_tokens * price.input
            + usage.output_tokens * price.output
            + usage.cache_creation_input_tokens * price.cache_write
            + usage.cache_read_input_tokens * price.cache_read
        )

    def _price(self, model: str) -> ModelPrice | None:
        """Exact id first, then the longest known id the model starts with, so a dated
        snapshot such as ``claude-opus-5-5-20261001`` still finds its family's price."""
        if model in self._prices:
            return self._prices[model]
        families = [known for known in self._prices if model.startswith(known + "-")]
        return self._prices[max(families, key=len)] if families else None
