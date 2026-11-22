"""Collect the results of one experiment run.

Run right after the run's build finishes (``perf/run.py`` does it
automatically). Dataflow keeps a finished job's history for only about 30
days, so this is what makes a run's numbers durable:

- throughput and correctness counts, from ``events_landing_perf``;
- the job's resource usage — Cloud Monitoring's ``dataflow.googleapis.com/
  job/total_*`` metrics (vCPU time, memory, disk, Streaming Engine data).
  ``gcloud beta dataflow metrics list`` does not carry these for streaming
  jobs, only watermark and lag figures;
- Cloud Monitoring time series: vCPUs, system lag, watermark age, the
  subscription backlog, and — for vertex runs — the endpoint's replicas,
  latency and CPU;
- a cost estimate from :mod:`perf.cost`.

Results go to BigQuery (``perf_runs``, ``perf_timeseries``) and to CSV
files under ``perf/results/``. Collecting a run again replaces its earlier
rows instead of adding duplicates.

Usage:
    python -m perf.collect --spec perf/results/specs/RUN.json --job-id JOB
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from perf import cost, gcp
from perf.experiment import PERF_LANDING_TABLE, RunSpec

RESULTS_DIR = Path(__file__).with_name("results")
REGION = "europe-central2"
MONITORING_URL = "https://monitoring.googleapis.com/v3/projects/{project}/timeSeries"

# Dataflow resource usage, job totals. Units from the metric descriptors:
# vCPU time in vCPU-seconds, memory and disk in GB-seconds, Streaming
# Engine data in bytes, SECU in Streaming Engine Compute Units.
RESOURCE_METRIC_PREFIX = "dataflow.googleapis.com/job/"
RESOURCE_METRICS = (
    "total_vcpu_time",
    "total_memory_usage_time",
    "total_pd_usage_time",
    "total_streaming_data_processed",
    "total_secu_usage",
    "total_shuffle_data_processed",
    "total_dcu_usage",
)
# Resource totals keep being reported for a few minutes after the job ends.
RESOURCE_GRACE_MINUTES = 15


@dataclass(frozen=True)
class SeriesSpec:
    """One Cloud Monitoring metric to capture for a run."""

    metric_type: str
    resource_filter: str  # format string: job_name, subscription_id, endpoint_id
    vertex_only: bool = False


SERIES = (
    SeriesSpec(
        "dataflow.googleapis.com/job/current_num_vcpus",
        'resource.labels.job_name = "{job_name}"',
    ),
    SeriesSpec(
        "dataflow.googleapis.com/job/system_lag",
        'resource.labels.job_name = "{job_name}"',
    ),
    SeriesSpec(
        "dataflow.googleapis.com/job/data_watermark_age",
        'resource.labels.job_name = "{job_name}"',
    ),
    SeriesSpec(
        "pubsub.googleapis.com/subscription/num_undelivered_messages",
        'resource.labels.subscription_id = "{subscription_id}"',
    ),
    SeriesSpec(
        "pubsub.googleapis.com/subscription/oldest_unacked_message_age",
        'resource.labels.subscription_id = "{subscription_id}"',
    ),
    SeriesSpec(
        "aiplatform.googleapis.com/prediction/online/replicas",
        'resource.labels.endpoint_id = "{endpoint_id}"',
        vertex_only=True,
    ),
    SeriesSpec(
        "aiplatform.googleapis.com/prediction/online/prediction_latencies",
        'resource.labels.endpoint_id = "{endpoint_id}"',
        vertex_only=True,
    ),
    SeriesSpec(
        "aiplatform.googleapis.com/prediction/online/cpu/utilization",
        'resource.labels.endpoint_id = "{endpoint_id}"',
        vertex_only=True,
    ),
)
REPLICAS_METRIC = "aiplatform.googleapis.com/prediction/online/replicas"


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested)
# ---------------------------------------------------------------------------


def resource_totals(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Reduce resource-metric samples to one total per metric.

    The ``job/total_*`` metrics are running totals, so the job's total is
    the largest sample.

    Args:
        rows: ``perf_timeseries``-shaped rows of ``job/total_*`` metrics.

    Returns:
        Short metric name (``total_vcpu_time`` …) → total.
    """
    totals: dict[str, float] = {}
    for row in rows:
        value = row["value"]
        if value is None:
            continue
        name = row["metric_type"].removeprefix(RESOURCE_METRIC_PREFIX)
        totals[name] = max(totals.get(name, value), value)
    return totals


def summarize_minutes(counts: list[int]) -> dict[str, float | int | None]:
    """Summarise per-minute row counts as throughput figures.

    Args:
        counts: Rows written in each active minute.

    Returns:
        ``active_minutes``, ``mean_rps``, ``p50_rps`` and ``peak_rps``
        (records per second); rates are ``None`` when nothing was written.
    """
    active = [c for c in counts if c > 0]
    if not active:
        return {
            "active_minutes": 0,
            "mean_rps": None,
            "p50_rps": None,
            "peak_rps": None,
        }
    return {
        "active_minutes": len(active),
        "mean_rps": round(sum(active) / len(active) / 60, 2),
        "p50_rps": round(statistics.median(active) / 60, 2),
        "peak_rps": round(max(active) / 60, 2),
    }


def point_value(value: dict[str, Any]) -> float | None:
    """Return a Monitoring point's value as a float (mean for distributions)."""
    if "doubleValue" in value:
        return float(value["doubleValue"])
    if "int64Value" in value:
        return float(value["int64Value"])
    if "distributionValue" in value:
        mean = value["distributionValue"].get("mean")
        return float(mean) if mean is not None else None
    if "boolValue" in value:
        return 1.0 if value["boolValue"] else 0.0
    return None


def parse_timeseries(
    run_id: str, metric_type: str, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Flatten a ``timeSeries.list`` response into ``perf_timeseries`` rows.

    Args:
        run_id: Run the samples belong to.
        metric_type: The requested metric type.
        payload: One page of the API response.

    Returns:
        One row per point.
    """
    rows: list[dict[str, Any]] = []
    for series in payload.get("timeSeries", []):
        labels = json.dumps(
            {
                **(series.get("resource", {}).get("labels") or {}),
                **(series.get("metric", {}).get("labels") or {}),
            },
            sort_keys=True,
        )
        for point in series.get("points", []):
            rows.append(
                {
                    "run_id": run_id,
                    "metric_type": metric_type,
                    "resource_labels": labels,
                    "point_time": point["interval"]["endTime"],
                    "value": point_value(point.get("value", {})),
                }
            )
    return rows


def parse_time(value: str) -> datetime:
    """Parse an RFC 3339 timestamp (with or without fractional seconds)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def series_points(
    rows: list[dict[str, Any]], metric_type: str
) -> list[tuple[datetime, float]]:
    """Return ``(time, value)`` samples of one metric from time-series rows."""
    return [
        (parse_time(r["point_time"]), r["value"])
        for r in rows
        if r["metric_type"] == metric_type and r["value"] is not None
    ]


def flatten_for_csv(row: dict[str, Any]) -> dict[str, Any]:
    """Return a ``perf_runs`` row with nested fields as JSON strings."""
    flat = dict(row)
    flat["job_metrics"] = json.dumps(
        {m["name"]: m["value"] for m in row.get("job_metrics", [])}, sort_keys=True
    )
    return flat


# ---------------------------------------------------------------------------
# GCP access
# ---------------------------------------------------------------------------


def fetch_series(
    project: str,
    token: str,
    spec: SeriesSpec,
    start: datetime,
    end: datetime,
    names: dict[str, str],
    run_id: str,
) -> list[dict[str, Any]]:
    """Fetch every point of one metric for the run's time window.

    Args:
        project: GCP project id.
        token: OAuth access token.
        spec: The metric to fetch.
        start: Window start.
        end: Window end.
        names: Values for the filter's placeholders.
        run_id: Run id stamped on each row.

    Returns:
        ``perf_timeseries`` rows; empty if the metric has no data.
    """
    params: dict[str, str] = {
        "filter": f'metric.type = "{spec.metric_type}" AND '
        + spec.resource_filter.format(**names),
        "interval.startTime": start.isoformat().replace("+00:00", "Z"),
        "interval.endTime": end.isoformat().replace("+00:00", "Z"),
        "view": "FULL",
    }
    rows: list[dict[str, Any]] = []
    while True:
        response = requests.get(
            MONITORING_URL.format(project=project),
            params=params,
            headers={"Authorization": f"Bearer {token}"},
            timeout=60,
        )
        if response.status_code != 200:
            print(
                f"  ! {spec.metric_type}: HTTP {response.status_code} "
                f"{response.text[:200]}",
                file=sys.stderr,
            )
            return rows
        payload = response.json()
        rows.extend(parse_timeseries(run_id, spec.metric_type, payload))
        page = payload.get("nextPageToken")
        if not page:
            return rows
        params["pageToken"] = page


def throughput(
    project: str, dataset: str, start: datetime, end: datetime
) -> dict[str, Any]:
    """Measure throughput and counts of what the run wrote.

    Args:
        project: GCP project id.
        dataset: Analytics dataset id.
        start: Job start.
        end: Job end.

    Returns:
        Throughput summary plus ``records_landed`` and
        ``distinct_ids_landed``.
    """
    table = f"`{project}.{dataset}.{PERF_LANDING_TABLE}`"
    window = (
        f"processed_at BETWEEN TIMESTAMP('{start.isoformat()}') "
        f"AND TIMESTAMP('{end.isoformat()}')"
    )
    per_minute = gcp.bq_query(
        project,
        f"SELECT TIMESTAMP_TRUNC(processed_at, MINUTE) AS m, COUNT(*) AS n "
        f"FROM {table} WHERE {window} GROUP BY m ORDER BY m",
    )
    totals = gcp.bq_query(
        project,
        f"SELECT COUNT(*) AS n, COUNT(DISTINCT id) AS d FROM {table} WHERE {window}",
    )[0]
    summary: dict[str, Any] = summarize_minutes([int(r["n"]) for r in per_minute])
    summary["records_landed"] = int(totals["n"])
    summary["distinct_ids_landed"] = int(totals["d"])
    return summary


def expected_records(project: str, dataset: str, staging_table: str) -> int:
    """Return the distinct ids in the staging table the run replayed."""
    rows = gcp.bq_query(
        project,
        f"SELECT COUNT(DISTINCT id) AS n FROM `{project}.{dataset}.{staging_table}`",
    )
    return int(rows[0]["n"])


def bq_load(project: str, dataset: str, table: str, rows: list[dict[str, Any]]) -> bool:
    """Append rows to a BigQuery table with ``bq load``.

    Returns:
        Whether the load succeeded (a missing table is reported, not raised,
        so the CSV copy is still written).
    """
    if not rows:
        return True
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
        path = handle.name
    try:
        gcp.run_text(
            [
                "bq",
                f"--project_id={project}",
                "load",
                "--source_format=NEWLINE_DELIMITED_JSON",
                f"{project}:{dataset}.{table}",
                path,
            ]
        )
        return True
    except gcp.CommandError as exc:
        print(f"  ! BigQuery load into {table} failed: {exc}", file=sys.stderr)
        return False
    finally:
        Path(path).unlink(missing_ok=True)


def write_csv(path: Path, rows: list[dict[str, Any]], *, replace_run: str) -> None:
    """Write rows to a CSV file, replacing any earlier rows of the same run.

    Args:
        path: CSV file; created with a header if missing.
        rows: Rows to write (all of run ``replace_run``).
        replace_run: Run id whose existing rows are dropped first.
    """
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    kept: list[dict[str, Any]] = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as handle:
            kept = [r for r in csv.DictReader(handle) if r.get("run_id") != replace_run]
    fieldnames = list(rows[0])
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(kept)
        writer.writerows(rows)


def delete_run_rows(project: str, dataset: str, run_id: str) -> None:
    """Delete a run's earlier rows from the BigQuery results tables."""
    for table in ("perf_runs", "perf_timeseries"):
        try:
            gcp.bq_execute(
                project,
                f"DELETE FROM `{project}.{dataset}.{table}` WHERE run_id = '{run_id}'",
            )
        except gcp.CommandError as exc:
            print(f"  ! could not clear {table} for {run_id}: {exc}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def collect_run(
    spec: RunSpec,
    job_id: str,
    *,
    build_id: str | None = None,
    git_commit: str | None = None,
    project: str | None = None,
    dataset: str = "co_analytics_dev",
    subscription_id: str = "co-events-dataflow-sub-dev",
    endpoint_id: str = "co-nlp-endpoint-dev",
    write_bigquery: bool = True,
) -> dict[str, Any]:
    """Collect and store the results of one run.

    Args:
        spec: The run's specification.
        job_id: Dataflow job id.
        build_id: Cloud Build id of the replay build.
        git_commit: Commit of the code that ran.
        project: GCP project id (gcloud's current project by default).
        dataset: Analytics dataset id.
        subscription_id: Pipeline input subscription (short id).
        endpoint_id: Vertex endpoint id (short id).
        write_bigquery: Also append to ``perf_runs`` / ``perf_timeseries``.

    Returns:
        The ``perf_runs`` row.
    """
    project = project or gcp.current_project()
    job = gcp.run_json(
        ["gcloud", "dataflow", "jobs", "describe", job_id, f"--region={REGION}"]
    )
    start = parse_time(job["createTime"])
    end = parse_time(job.get("currentStateTime") or datetime.now(UTC).isoformat())
    print(f"Collecting {spec.run_id}: job {job['name']} {start:%H:%M}–{end:%H:%M} UTC")

    token = gcp.access_token()
    names = {
        "job_name": job["name"],
        "subscription_id": subscription_id,
        "endpoint_id": endpoint_id,
    }

    resource_rows: list[dict[str, Any]] = []
    for metric in RESOURCE_METRICS:
        resource_rows.extend(
            fetch_series(
                project,
                token,
                SeriesSpec(
                    RESOURCE_METRIC_PREFIX + metric,
                    'resource.labels.job_name = "{job_name}"',
                ),
                start,
                end + timedelta(minutes=RESOURCE_GRACE_MINUTES),
                names,
                spec.run_id,
            )
        )
    job_metrics = resource_totals(resource_rows)

    series_rows: list[dict[str, Any]] = []
    for series in SERIES:
        if series.vertex_only and spec.model != "vertex":
            continue
        series_rows.extend(
            fetch_series(project, token, series, start, end, names, spec.run_id)
        )

    used_replica_hours = cost.replica_hours(series_points(series_rows, REPLICAS_METRIC))
    total_cost, cost_lines = cost.estimate(
        job_metrics, used_replica_hours, cost.load_prices()
    )

    row: dict[str, Any] = {
        "run_id": spec.run_id,
        "experiment": spec.experiment,
        "build_id": build_id,
        "job_id": job_id,
        "job_name": job["name"],
        "git_commit": git_commit,
        "started_at": start.isoformat(),
        "finished_at": end.isoformat(),
        "model": spec.model,
        "speedup": spec.speedup,
        "max_workers": spec.num_workers or spec.max_workers,
        "num_workers": spec.num_workers,
        "machine_type": spec.machine_type,
        "max_batch_size": spec.max_batch_size,
        "endpoint_replicas": spec.endpoint_replicas,
        "staging_table": spec.staging_table,
        "copies": spec.copies,
        "records_expected": expected_records(project, dataset, spec.staging_table),
        **throughput(project, dataset, start, end),
        "job_metrics": [
            {"name": k, "value": v} for k, v in sorted(job_metrics.items())
        ],
        "estimated_cost_usd": round(total_cost, 4) if total_cost is not None else None,
        "notes": spec.notes,
        "collected_at": datetime.now(UTC).isoformat(),
    }

    all_series = series_rows + resource_rows
    write_csv(RESULTS_DIR / "runs.csv", [flatten_for_csv(row)], replace_run=spec.run_id)
    timeseries_csv = RESULTS_DIR / "timeseries" / f"{spec.run_id}.csv"
    timeseries_csv.unlink(missing_ok=True)
    write_csv(timeseries_csv, all_series, replace_run=spec.run_id)
    if write_bigquery:
        delete_run_rows(project, dataset, spec.run_id)
        bq_load(project, dataset, "perf_runs", [row])
        bq_load(project, dataset, "perf_timeseries", all_series)

    print(
        f"  landed {row['records_landed']} / expected {row['records_expected']}, "
        f"mean {row['mean_rps']} rec/s, peak {row['peak_rps']} rec/s"
    )
    for line in cost_lines:
        print(f"  {line.component}: {line.quantity:.3f} {line.unit} = {line.cost:.4f}")
    if total_cost is None:
        print("  cost: not estimated — fill in perf/prices.yaml")
    else:
        print(f"  estimated cost: {total_cost:.4f} USD")
    return row


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--spec", type=Path, required=True, help="Run spec JSON.")
    parser.add_argument("--job-id", required=True, help="Dataflow job id.")
    parser.add_argument("--build-id", help="Cloud Build id, if known.")
    parser.add_argument("--git-commit", help="Commit of the code that ran.")
    parser.add_argument(
        "--no-bigquery", action="store_true", help="Write CSV files only."
    )
    args = parser.parse_args(argv)

    collect_run(
        RunSpec.from_file(args.spec),
        args.job_id,
        build_id=args.build_id,
        git_commit=args.git_commit,
        write_bigquery=not args.no_bigquery,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
