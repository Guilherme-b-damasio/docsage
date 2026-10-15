import pytest

from docsage.domain.models import TokenUsage
from docsage.infrastructure.pricing import ModelPrice, PriceTable


def test_prices_every_kind_of_token():
    table = PriceTable({"m": ModelPrice(input=4.0, output=20.0, cache_read=0.2)})
    usage = TokenUsage(
        model="m",
        input_tokens=1_000_000,
        output_tokens=100_000,
        cache_creation_input_tokens=200_000,
        cache_read_input_tokens=500_000,
    )

    # 4.00 input + 2.00 output + 1.00 cache write (1.25x input) + 0.10 cache read
    assert table.estimate(usage) == pytest.approx(7.10)


def test_default_table_prices_the_default_model():
    usage = TokenUsage(model="claude-opus-5-5", input_tokens=1000, output_tokens=500)

    assert PriceTable().estimate(usage) == pytest.approx(0.014)


def test_unknown_models_have_no_price():
    usage = TokenUsage(model="someone-elses-model", input_tokens=10, output_tokens=10)

    assert PriceTable().estimate(usage) is None


def test_dated_snapshots_use_the_longest_matching_family():
    table = PriceTable(
        {
            "claude-opus-5": ModelPrice(input=5.0, output=25.0, cache_read=0.5),
            "claude-opus-5-5": ModelPrice(input=4.0, output=20.0, cache_read=0.2),
        }
    )
    usage = TokenUsage(model="claude-opus-5-5-20261001", input_tokens=1_000_000, output_tokens=0)

    assert table.estimate(usage) == pytest.approx(4.0)


def test_an_empty_table_prices_nothing():
    usage = TokenUsage(model="claude-opus-5-5", input_tokens=10, output_tokens=10)

    assert PriceTable({}).estimate(usage) is None
