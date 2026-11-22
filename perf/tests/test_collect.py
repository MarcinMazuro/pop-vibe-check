import json
from datetime import UTC, datetime
from typing import Any

from perf.collect import (
    flatten_for_csv,
    parse_timeseries,
    point_value,
    resource_totals,
    series_points,
    summarize_minutes,
    write_csv,
)

VCPU = "dataflow.googleapis.com/job/total_vcpu_time"
MEMORY = "dataflow.googleapis.com/job/total_memory_usage_time"


def test_resource_totals_take_the_largest_running_total_per_metric():
    rows: list[dict[str, Any]] = [
        {"metric_type": VCPU, "value": 940.0},
        {"metric_type": VCPU, "value": 600.0},
        {"metric_type": MEMORY, "value": 3760.0},
        {"metric_type": MEMORY, "value": None},
    ]

    assert resource_totals(rows) == {
        "total_vcpu_time": 940.0,
        "total_memory_usage_time": 3760.0,
    }


def test_write_csv_replaces_rows_of_the_same_run(tmp_path):
    path = tmp_path / "runs.csv"
    write_csv(path, [{"run_id": "a", "x": "1"}], replace_run="a")
    write_csv(path, [{"run_id": "b", "x": "2"}], replace_run="b")
    write_csv(path, [{"run_id": "a", "x": "3"}], replace_run="a")

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines == ["run_id,x", "b,2", "a,3"]


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
