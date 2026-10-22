from docsage.domain.models import TokenUsage
from docsage.infrastructure.units import human_size, indexed_label, usage_summary


def test_human_size_picks_the_largest_fitting_unit():
    assert (human_size(512), human_size(1536), human_size(2 * 1024 * 1024)) == (
        "512 B",
        "1.5 KB",
        "2.0 MB",
    )


def test_usage_summary_counts_every_input_token_and_names_the_cached_ones():
    usage = TokenUsage(
        model="claude-opus-5-5",
        input_tokens=300,
        output_tokens=85,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=900,
    )

    assert usage_summary(usage, 0.00353) == (
        "claude-opus-5-5: 1,200 input tokens (900 cached), 85 output tokens, ~$0.0035"
    )


def test_usage_summary_leaves_out_an_unknown_price():
    usage = TokenUsage(model="other", input_tokens=10, output_tokens=1)

    assert usage_summary(usage, None) == "other: 10 input tokens, 1 output tokens"


def test_indexed_label_shows_the_minute_in_utc():
    assert indexed_label("2026-10-22T09:30:15+00:00") == "2026-10-22 09:30 UTC"
    assert indexed_label("2026-10-22T09:30:15-03:00") == "2026-10-22 12:30 UTC"


def test_indexed_label_of_a_missing_or_unreadable_time():
    assert indexed_label("") == "unknown"
    assert indexed_label("yesterday") == "yesterday"
