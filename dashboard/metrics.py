"""Totals over rows of the reporting views.

The metrics themselves are view columns (``definitions/reporting/``). What
is left here is summing a selection of rows — the sources a viewer picked —
and dividing again, the same thing a Looker Studio scorecard does with SUM
fields, so the shares stay exact.
"""

from __future__ import annotations

import pandas as pd

COUNT_COLUMNS = ["records", "positive", "neutral", "negative"]


def with_shares(df: pd.DataFrame) -> pd.DataFrame:
    """Add the share and net-sentiment columns computed from the counts."""
    records = df["records"].where(df["records"] > 0)
    return df.assign(
        positive_share=df["positive"] / records,
        neutral_share=df["neutral"] / records,
        negative_share=df["negative"] / records,
        # Positive minus negative, in [-1, 1] — same definition as the views.
        net_sentiment=(df["positive"] - df["negative"]) / records,
    )


def totals(rows: pd.DataFrame) -> pd.Series:
    """Single-row sum of the counts in ``rows``: the headline numbers.

    ``rows`` must not overlap — one grain of ``v_sentiment_by_period``, not
    all three.
    """
    summed = rows[COUNT_COLUMNS].sum().to_frame().T
    return with_shares(summed).iloc[0]
