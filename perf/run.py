r"""Run one performance experiment end to end.

Submits the replay build (``dataflow/replay.cloudbuild.yaml``) from this
working tree with the experiment's parameters, waits for it, then
collects the results with :mod:`perf.collect`.

Why the replay build: it already launches the job, runs the publisher,
waits until every record has landed, and — the part that protects the
budget — always drains the streaming job, even when something fails.

The infrastructure values (subscription, worker service account, …) are
read from the ``co-replay-dev`` trigger, where Terraform put them, so
nothing here is hardcoded and Terraform does not need to be installed.

COST. Every run starts a streaming Dataflow job; a vertex run also needs
a deployed endpoint, which bills until it is undeployed. The script shows
what it is about to start and asks first; ``--yes`` skips the question.

Usage:
    python -m perf.run --experiment e1 --run-id e1-w2-s5000 \\
        --model stub --speedup 5000 --max-workers 2
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

from perf import gcp
from perf.collect import REGION, RESULTS_DIR, collect_run
from perf.experiment import (
    ALLOWED_STAGING_TABLES,
    MODELS,
    REAL_STAGING_TABLE,
    RunSpec,
    substitutions_arg,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
TRIGGER = "co-replay-dev"
BUILD_CONFIG = "dataflow/replay.cloudbuild.yaml"
TERMINAL_BUILD_STATES = {
    "SUCCESS",
    "FAILURE",
    "INTERNAL_ERROR",
    "TIMEOUT",
    "CANCELLED",
    "EXPIRED",
}
POLL_SECONDS = 60


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Run one performance experiment.")
    parser.add_argument("--experiment", required=True, help="e1 … e6")
    parser.add_argument("--run-id", required=True, help="Unique, e.g. e1-w2-s5000")
    parser.add_argument("--model", choices=MODELS, default="stub")
    parser.add_argument("--speedup", type=float, help="Publisher time compression.")
    parser.add_argument("--max-sleep-seconds", type=float)
    parser.add_argument("--max-workers", type=int, default=2)
    parser.add_argument(
        "--num-workers", type=int, help="Fixed worker count, autoscaling off."
    )
    parser.add_argument("--machine-type", default="e2-standard-2")
    parser.add_argument("--max-batch-size", type=int)
    parser.add_argument(
        "--staging-table", choices=ALLOWED_STAGING_TABLES, default=REAL_STAGING_TABLE
    )
    parser.add_argument("--copies", type=int, default=1, help="Amplification factor.")
    parser.add_argument("--endpoint-replicas", type=int, help="Recorded, not applied.")
    parser.add_argument("--wait-timeout-minutes", type=int, default=180)
    parser.add_argument("--notes", default="")
    parser.add_argument("--yes", action="store_true", help="Do not ask to confirm.")
    parser.add_argument("--no-bigquery", action="store_true", help="CSV results only.")
    return parser.parse_args(argv)


def spec_from_args(args: argparse.Namespace) -> RunSpec:
    """Build the run specification from parsed arguments."""
    return RunSpec(
        experiment=args.experiment,
        run_id=args.run_id,
        model=args.model,
        speedup=args.speedup,
        max_workers=args.max_workers,
        num_workers=args.num_workers,
        machine_type=args.machine_type,
        max_batch_size=args.max_batch_size,
        staging_table=args.staging_table,
        copies=args.copies,
        max_sleep_seconds=args.max_sleep_seconds,
        wait_timeout_minutes=args.wait_timeout_minutes,
        endpoint_replicas=args.endpoint_replicas,
        notes=args.notes,
    )


def git_commit() -> str:
    """Return HEAD, marked ``-dirty`` when the working tree has changes."""
    head = gcp.run_text(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"])
    dirty = gcp.run_text(["git", "-C", str(REPO_ROOT), "status", "--porcelain"])
    return f"{head}-dirty" if dirty else head


def trigger_config() -> dict[str, Any]:
    """Return the replay trigger's definition."""
    trigger: dict[str, Any] = gcp.run_json(
        ["gcloud", "builds", "triggers", "describe", TRIGGER, f"--region={REGION}"]
    )
    return trigger


def wait_for_build(build_id: str) -> str:
    """Poll a build until it finishes and return its final status."""
    while True:
        status = gcp.run_text(
            [
                "gcloud",
                "builds",
                "describe",
                build_id,
                f"--region={REGION}",
                "--format=value(status)",
            ]
        )
        print(f"  {time.strftime('%H:%M:%S')} build {status}")
        if status in TERMINAL_BUILD_STATES:
            return status
        time.sleep(POLL_SECONDS)


def find_job_id(build_id: str) -> str | None:
    """Return the id of the Dataflow job the replay build launched.

    The build names its job ``co-replay-<BUILD_ID>``.
    """
    jobs = gcp.run_json(
        [
            "gcloud",
            "dataflow",
            "jobs",
            "list",
            f"--region={REGION}",
            "--status=all",
            f"--filter=name=co-replay-{build_id}",
        ]
    )
    return str(jobs[0]["id"]) if jobs else None


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    args = parse_args(argv)
    spec = spec_from_args(args)
    project = gcp.current_project()
    trigger = trigger_config()
    substitutions = spec.substitutions(trigger.get("substitutions") or {}, project)
    service_account = trigger["serviceAccount"]
    commit = git_commit()

    workers = (
        f"exactly {spec.num_workers} (autoscaling off)"
        if spec.num_workers
        else f"up to {spec.max_workers}"
    )
    print(
        f"""
About to run experiment {spec.experiment} / {spec.run_id} in {project}.
It starts a STREAMING Dataflow job (drained by the build when done).

  model          {spec.model}
  speedup        {spec.speedup or 'publisher default'}
  workers        {workers} x {spec.machine_type}
  batch size     {spec.max_batch_size or 'template default'}
  staging table  {spec.staging_table} (copies: {spec.copies})
  writes to      {substitutions['_OUTPUT_TABLE']} (never promoted)
  code           {commit}
"""
    )
    if spec.model == "vertex":
        print(
            "  The vertex endpoint must already be deployed — and undeployed after.\n"
        )
    if not args.yes and input("Start? [y/N] ").strip().lower() != "y":
        print("Aborted.")
        return 1

    specs_dir = RESULTS_DIR / "specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    spec_path = specs_dir / f"{spec.run_id}.json"
    if spec_path.exists():
        print(f"{spec_path} exists — run ids must be unique.", file=sys.stderr)
        return 2
    spec_path.write_text(spec.to_json() + "\n", encoding="utf-8")

    build = gcp.run_json(
        [
            "gcloud",
            "builds",
            "submit",
            str(REPO_ROOT),
            f"--config={REPO_ROOT / BUILD_CONFIG}",
            f"--region={REGION}",
            f"--service-account={service_account}",
            f"--substitutions={substitutions_arg(substitutions)}",
            "--async",
        ]
    )
    build_id = str(build["id"])
    print(f"Build {build_id} submitted.")

    status = wait_for_build(build_id)
    job_id = find_job_id(build_id)
    if job_id is None:
        print(
            "The build launched no Dataflow job; nothing to collect.", file=sys.stderr
        )
        return 1

    collect_run(
        spec,
        job_id,
        build_id=build_id,
        git_commit=commit,
        project=project,
        dataset=substitutions["_DATASET"],
        subscription_id=substitutions["_INPUT_SUBSCRIPTION"].rsplit("/", 1)[-1],
        endpoint_id=(substitutions.get("_VERTEX_ENDPOINT_ID") or "").rsplit("/", 1)[-1],
        write_bigquery=not args.no_bigquery,
    )
    if status != "SUCCESS":
        print(
            f"Build finished {status}: results above may be partial.", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
