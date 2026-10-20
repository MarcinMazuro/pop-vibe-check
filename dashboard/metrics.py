"""Re-aggregation of the reporting views' additive counts.

``v_sentiment_daily`` is one row per day × source × event_tag. Rolling it up
to a week, a month or a whole event only ever *sums* its counts and divides
again — the same thing a Looker Studio chart does with SUM fields — so the
shares stay exact. Non-additive columns are either re-weighted
(``avg_confidence``, by records) or dropped (``distinct_authors``: an author
active on two days would be counted twice).
"""

from __future__ import annotations

from typing import Literal

import pandas as pd

COUNT_COLUMNS = ["records", "positive", "neutral", "negative"]

Grain = Literal["D", "W", "M"]


def with_shares(df: pd.DataFrame) -> pd.DataFrame:
    """Add the share and net-sentiment columns computed from the counts."""
    records = df["records"].where(df["records"] > 0)
    return df.assign(
        positive_share=df["positive"] / records,
        neutral_share=df["neutral"] / records,
        negative_share=df["negative"] / records,
        # Positive minus negative, in [-1, 1] — same definition as the view.
        net_sentiment=(df["positive"] - df["negative"]) / records,
    )


def rollup(
    daily: pd.DataFrame, by: list[str], grain: Grain | None = None
) -> pd.DataFrame:
    """Sum the counts over everything not in ``by`` and recompute the shares.

    Args:
        daily: Rows of ``v_sentiment_daily``, ``event_date`` as datetime.
        by: Columns to keep, e.g. ``["source"]`` or ``["event_tag", "source"]``.
        grain: When given, ``event_date`` is bucketed to the start of its day,
            week (Monday) or month and kept as a ``period`` column.

    Returns:
        One row per group with the summed counts, ``avg_confidence`` weighted
        by records, and the shares from :func:`with_shares`.
    """
    frame = daily.assign(_confidence_mass=daily["avg_confidence"] * daily["records"])
    keys = list(by)
    if grain is not None:
        frame["period"] = frame["event_date"].dt.to_period(grain).dt.start_time
        keys = ["period", *keys]

    summed = frame.groupby(keys, as_index=False, dropna=False)[
        [*COUNT_COLUMNS, "_confidence_mass"]
    ].sum()
    summed["avg_confidence"] = summed.pop("_confidence_mass") / summed["records"]
    return with_shares(summed)


def complete_periods(series: pd.DataFrame, by: str, grain: Grain) -> pd.DataFrame:
    """Give every group a row for every period, zero counts where it had none.

    A line through the result breaks where a group was silent instead of
    drawing a straight segment across months without data; the empty rows'
    shares are undefined (NaN), not zero.

    Args:
        series: Output of ``rollup(..., [by], grain)``.
        by: The one grouping column besides ``period``.
        grain: The grain ``series`` was rolled up with.
    """
    if series.empty:
        return series
    periods = pd.period_range(
        series["period"].min(), series["period"].max(), freq=grain
    ).start_time
    full = pd.MultiIndex.from_product(
        [periods, series[by].unique()], names=["period", by]
    )
    out = series.set_index(["period", by]).reindex(full)
    out[COUNT_COLUMNS] = out[COUNT_COLUMNS].fillna(0).astype("int64")
    return with_shares(out.reset_index())


def totals(daily: pd.DataFrame) -> pd.Series:
    """Single-row rollup of everything in ``daily``: the headline numbers."""
    summed = daily[COUNT_COLUMNS].sum().to_frame().T
    return with_shares(summed).iloc[0]


def source_divergence(by_event_source: pd.DataFrame) -> pd.DataFrame:
    """Per event, the gap between the most and least positive source.

    Only events covered by at least two sources have a gap. Sorted with the
    widest gap first — the events where single-source analysis would mislead.

    Args:
        by_event_source: Output of ``rollup(daily, ["event_tag", "source"])``.

    Returns:
        Columns ``event_tag``, ``high_source``, ``high_net``, ``low_source``,
        ``low_net``, ``gap``.
    """
    rows = []
    for tag, group in by_event_source.groupby("event_tag"):
        if group["source"].nunique() < 2:
            continue
        ranked = group.sort_values("net_sentiment", ascending=False)
        high, low = ranked.iloc[0], ranked.iloc[-1]
        rows.append(
            {
                "event_tag": tag,
                "high_source": high["source"],
                "high_net": high["net_sentiment"],
                "low_source": low["source"],
                "low_net": low["net_sentiment"],
                "gap": high["net_sentiment"] - low["net_sentiment"],
            }
        )
    columns = ["event_tag", "high_source", "high_net", "low_source", "low_net", "gap"]
    return (
        pd.DataFrame(rows, columns=columns)
        .sort_values("gap", ascending=False)
        .reset_index(drop=True)
    )
