"""Tests for the re-aggregation of the reporting views' counts."""

import pytest

pd = pytest.importorskip("pandas")

from dashboard import metrics  # noqa: E402


def _daily(rows):
    df = pd.DataFrame(
        rows,
        columns=[
            "event_date",
            "source",
            "event_tag",
            "records",
            "positive",
            "neutral",
            "negative",
            "avg_confidence",
        ],
    )
    df["event_date"] = pd.to_datetime(df["event_date"])
    return df


DAILY = _daily(
    [
        # Monday and Wednesday of one week, Monday of the next.
        ("2025-04-21", "steam", "launch", 10, 8, 1, 1, 0.9),
        ("2025-04-23", "steam", "launch", 30, 15, 5, 10, 0.7),
        ("2025-04-28", "steam", "general", 4, 1, 1, 2, 0.5),
        ("2025-04-23", "youtube", "launch", 20, 5, 5, 10, 0.8),
    ]
)


def test_rollup_sums_counts_and_recomputes_shares():
    out = metrics.rollup(DAILY, ["event_tag", "source"])
    launch = out[(out.event_tag == "launch") & (out.source == "steam")].iloc[0]

    assert launch.records == 40
    assert launch.positive == 23
    assert launch.negative == 11
    # The share of the sum, not the mean of the daily shares.
    assert launch.positive_share == pytest.approx(23 / 40)
    assert launch.net_sentiment == pytest.approx((23 - 11) / 40)


def test_rollup_weights_confidence_by_records():
    out = metrics.rollup(DAILY, ["event_tag", "source"])
    launch = out[(out.event_tag == "launch") & (out.source == "steam")].iloc[0]

    assert launch.avg_confidence == pytest.approx((10 * 0.9 + 30 * 0.7) / 40)


def test_rollup_buckets_weeks_from_monday():
    out = metrics.rollup(DAILY, ["source"], grain="W")
    steam = out[out.source == "steam"].sort_values("period")

    assert steam.period.dt.strftime("%Y-%m-%d").tolist() == [
        "2025-04-21",
        "2025-04-28",
    ]
    assert steam.records.tolist() == [40, 4]


def test_rollup_drops_non_additive_author_counts():
    out = metrics.rollup(DAILY.assign(distinct_authors=1), ["source"])

    assert "distinct_authors" not in out.columns


def test_totals():
    total = metrics.totals(DAILY)

    assert total.records == 64
    assert total.net_sentiment == pytest.approx((29 - 23) / 64)


def test_with_shares_leaves_empty_groups_undefined():
    out = metrics.with_shares(
        pd.DataFrame({"records": [0], "positive": [0], "neutral": [0], "negative": [0]})
    )

    assert out.net_sentiment.isna().all()


def test_source_divergence_ranks_widest_gap_first():
    by_event = metrics.rollup(DAILY, ["event_tag", "source"])
    gaps = metrics.source_divergence(by_event)

    # 'general' has one source only, so it has no gap.
    assert gaps.event_tag.tolist() == ["launch"]
    top = gaps.iloc[0]
    assert top.high_source == "steam"
    assert top.low_source == "youtube"
    assert top.gap == pytest.approx((23 - 11) / 40 - (5 - 10) / 20)


def test_source_divergence_empty_when_single_source():
    by_event = metrics.rollup(DAILY[DAILY.source == "steam"], ["event_tag", "source"])

    assert metrics.source_divergence(by_event).empty


def test_event_lift_compares_against_the_rest_of_the_source():
    lift = metrics.event_lift(DAILY)
    steam = lift[(lift.event_tag == "launch") & (lift.source == "steam")].iloc[0]

    # Two days with data in the window, one in the baseline ('general').
    assert steam.days == 2
    assert steam.baseline_days == 1
    assert steam.baseline_net_sentiment == pytest.approx((1 - 2) / 4)
    assert steam.net_lift == pytest.approx((23 - 11) / 40 - (1 - 2) / 4)
    assert steam.volume_multiplier == pytest.approx((40 / 2) / (4 / 1))


def test_event_lift_skips_the_background_tag():
    lift = metrics.event_lift(DAILY)

    assert "general" not in set(lift.event_tag)


def test_event_lift_without_baseline_is_undefined():
    # YouTube's only records are the launch window: nothing to compare with.
    lift = metrics.event_lift(DAILY)
    youtube = lift[lift.source == "youtube"].iloc[0]

    assert youtube.baseline_records == 0
    assert pd.isna(youtube.net_lift)
    assert pd.isna(youtube.volume_multiplier)


def test_event_lift_baseline_on_youtube_is_the_other_events():
    events_only = _daily(
        [
            ("2025-04-23", "youtube", "launch", 20, 5, 5, 10, 0.8),
            ("2025-06-01", "youtube", "reveal", 10, 8, 2, 0, 0.8),
            ("2025-06-02", "youtube", "reveal", 10, 6, 4, 0, 0.8),
        ]
    )
    lift = metrics.event_lift(events_only).set_index("event_tag")

    assert lift.loc["launch", "baseline_net_sentiment"] == pytest.approx(14 / 20)
    assert lift.loc["launch", "volume_multiplier"] == pytest.approx(20 / 10)


def test_complete_periods_breaks_lines_across_silent_weeks():
    sparse = _daily(
        [
            ("2025-04-21", "youtube", "launch", 10, 5, 0, 5, 0.8),
            ("2025-05-05", "youtube", "launch", 10, 10, 0, 0, 0.8),
        ]
    )
    weekly = metrics.rollup(sparse, ["source"], grain="W")
    out = metrics.complete_periods(weekly, "source", "W")

    assert out.period.dt.strftime("%Y-%m-%d").tolist() == [
        "2025-04-21",
        "2025-04-28",
        "2025-05-05",
    ]
    assert out.records.tolist() == [10, 0, 10]
    # The silent week has no sentiment, not a sentiment of zero.
    assert out.net_sentiment.isna().tolist() == [False, True, False]
