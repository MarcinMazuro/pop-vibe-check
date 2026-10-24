"""Tests for the totals over the reporting views' counts."""

import pytest

pd = pytest.importorskip("pandas")

from dashboard import metrics  # noqa: E402

# Month rows of v_sentiment_by_period: two sources, one empty month.
MONTHS = pd.DataFrame(
    {
        "period": ["2025-04-01", "2025-04-01", "2025-05-01", "2025-05-01"],
        "source": ["steam", "youtube", "steam", "youtube"],
        "records": [40, 20, 4, 0],
        "positive": [23, 5, 1, 0],
        "neutral": [6, 5, 1, 0],
        "negative": [11, 10, 2, 0],
    }
)


def test_totals_sum_counts_and_recompute_shares():
    total = metrics.totals(MONTHS)

    assert total.records == 64
    assert total.positive_share == pytest.approx(29 / 64)
    # The share of the sum, not the mean of the rows' shares.
    assert total.net_sentiment == pytest.approx((29 - 23) / 64)


def test_totals_of_one_source():
    total = metrics.totals(MONTHS[MONTHS.source == "youtube"])

    assert total.records == 20
    assert total.net_sentiment == pytest.approx((5 - 10) / 20)


def test_with_shares_leaves_empty_groups_undefined():
    out = metrics.with_shares(
        pd.DataFrame({"records": [0], "positive": [0], "neutral": [0], "negative": [0]})
    )

    assert out.net_sentiment.isna().all()
