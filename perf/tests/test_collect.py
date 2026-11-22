import json
from datetime import UTC, datetime
from typing import Any

from perf.collect import (
    flatten_for_csv,
    parse_job_metrics,
    parse_timeseries,
    point_value,
    series_points,
    summarize_minutes,
)


def test_parse_job_metrics_keeps_job_level_scalars_only():
    entries = [
        {"name": {"name": "TotalVcpuTime", "origin": "dataflow/v1b3"}, "scalar": 7200},
        {
            "name": {"name": "TotalVcpuTime", "context": {"tentative": "true"}},
            "scalar": 7100,
        },
        {"name": {"name": "ElementCount", "context": {"step": "s1"}}, "scalar": 99},
        {"name": {"name": "TotalMemoryUsage"}, "scalar": 1.5e6},
        {"name": {"name": "MeanByteCount"}, "distribution": {"count": 3}},
        {"name": {"name": "Flag"}, "scalar": True},
    ]

    assert parse_job_metrics(entries) == {
        "TotalVcpuTime": 7200.0,
        "TotalMemoryUsage": 1.5e6,
    }


def test_parse_job_metrics_handles_no_output():
    assert parse_job_metrics(None) == {}


def test_summarize_minutes():
    summary = summarize_minutes([600, 1200, 0, 1800])

    assert summary == {
        "active_minutes": 3,
        "mean_rps": 20.0,
        "p50_rps": 20.0,
        "peak_rps": 30.0,
    }


def test_summarize_minutes_without_rows():
    assert summarize_minutes([])["mean_rps"] is None


def test_point_value_variants():
    assert point_value({"doubleValue": 0.5}) == 0.5
    assert point_value({"int64Value": "3"}) == 3.0
    assert point_value({"distributionValue": {"mean": 12.5}}) == 12.5
    assert point_value({"boolValue": True}) == 1.0
    assert point_value({}) is None


def test_parse_timeseries_flattens_points_with_labels():
    payload = {
        "timeSeries": [
            {
                "resource": {"labels": {"job_name": "co-replay-1"}},
                "metric": {"labels": {"region": "europe-central2"}},
                "points": [
                    {
                        "interval": {"endTime": "2026-11-22T10:01:00Z"},
                        "value": {"int64Value": "2"},
                    },
                    {
                        "interval": {"endTime": "2026-11-22T10:00:00Z"},
                        "value": {"int64Value": "1"},
                    },
                ],
            }
        ]
    }

    rows = parse_timeseries("e1-a", "m/vcpus", payload)

    assert [r["value"] for r in rows] == [2.0, 1.0]
    assert rows[0]["run_id"] == "e1-a"
    assert json.loads(rows[0]["resource_labels"]) == {
        "job_name": "co-replay-1",
        "region": "europe-central2",
    }


def test_series_points_filters_by_metric_and_parses_time():
    rows: list[dict[str, Any]] = [
        {"metric_type": "a", "point_time": "2026-11-22T10:00:00Z", "value": 1.0},
        {"metric_type": "b", "point_time": "2026-11-22T10:00:00Z", "value": 5.0},
        {"metric_type": "a", "point_time": "2026-11-22T10:01:00Z", "value": None},
    ]

    assert series_points(rows, "a") == [(datetime(2026, 11, 22, 10, tzinfo=UTC), 1.0)]


def test_flatten_for_csv_serialises_job_metrics():
    row = {"run_id": "r", "job_metrics": [{"name": "TotalVcpuTime", "value": 1.0}]}

    assert flatten_for_csv(row)["job_metrics"] == '{"TotalVcpuTime": 1.0}'
