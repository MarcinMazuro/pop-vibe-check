r"""Copy runs from the Workbench-local MLflow file store to the MLflow server.

Before the tracking server existed, run metadata lived in a file store on
the Workbench disk (``/home/jupyter/mlruns``) and only the artifacts were
in GCS. This copies every experiment and run into the server: tags,
params, the full metric history, start/end times and status. MLflow
assigns new run ids on the server; the old id and artifact URI are kept as
the tags ``migrated_from_run_id`` and ``migrated_from_artifact_uri``.

Artifacts are copied inside GCS to the new run's artifact URI (a
server-side rewrite, nothing is downloaded). The originals are left in
place: delete them by hand once the copies are checked in the UI. With
``--no-copy-artifacts`` only the tag points at them.

Re-running is safe: a run whose ``migrated_from_run_id`` already exists on
the server is skipped.

Run on Workbench, as the trainer SA (``roles/iap.httpsResourceAccessor``
plus objectAdmin on the artifacts bucket)::

    export MLFLOW_TRACKING_URI=https://co-mlflow-dev-....run.app
    export MLFLOW_IAP_AUDIENCE=<IAP OAuth client ID>
    python -m nlp.tracking.migrate --source /home/jupyter/mlruns --dry-run
    python -m nlp.tracking.migrate --source /home/jupyter/mlruns
"""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any, TypeVar

from nlp.tracking.mlflow_utils import IAP_AUDIENCE_ENV, use_iap_token

logger = logging.getLogger(__name__)

T = TypeVar("T")

MIGRATED_FROM_RUN_ID = "migrated_from_run_id"
MIGRATED_FROM_ARTIFACT_URI = "migrated_from_artifact_uri"
MIGRATED_FROM_STATUS = "migrated_from_status"

# log_batch limits on the REST API.
MAX_PARAMS_PER_BATCH = 100
MAX_METRICS_PER_BATCH = 1000


def chunked(items: Sequence[T], size: int) -> Iterator[list[T]]:
    """Yield consecutive slices of at most ``size`` items.

    Args:
        items: The sequence to split.
        size: Largest slice length.

    Yields:
        Lists of at most ``size`` items, in order.
    """
    for start in range(0, len(items), size):
        yield list(items[start : start + size])


def split_gs_uri(uri: str) -> tuple[str, str]:
    """Split ``gs://bucket/prefix`` into bucket and prefix.

    Args:
        uri: A ``gs://`` URI.

    Returns:
        ``(bucket, prefix)``; the prefix has no leading or trailing slash.

    Raises:
        ValueError: If ``uri`` is not a ``gs://`` URI with a bucket.
    """
    if not uri.startswith("gs://"):
        raise ValueError(f"Not a gs:// URI: {uri!r}")
    bucket, _, prefix = uri[len("gs://") :].partition("/")
    if not bucket:
        raise ValueError(f"No bucket in {uri!r}")
    return bucket, prefix.strip("/")


def terminal_status(status: str) -> tuple[str, bool]:
    """Return the status to record on the server, and whether it changed.

    A run still ``RUNNING`` in the file store is one whose process died
    without closing it; nothing will finish it now. It is recorded as
    ``KILLED`` and the original status kept in a tag, rather than shown on
    the server as forever in progress.

    Args:
        status: Run status in the file store (``FINISHED``, ``RUNNING``, …).

    Returns:
        ``(status_to_set, changed)``.
    """
    if status in {"RUNNING", "SCHEDULED"}:
        return "KILLED", True
    return status, False


def copy_artifacts(source_uri: str, target_uri: str, *, dry_run: bool) -> int:
    """Copy every object under ``source_uri`` to the same path under ``target_uri``.

    Uses GCS rewrite, so the bytes never leave Google; large objects take
    several rewrite calls, which the loop follows.

    Args:
        source_uri: The old run's artifact URI.
        target_uri: The new run's artifact URI.
        dry_run: Count objects without copying.

    Returns:
        Number of objects copied (or that would be).
    """
    from google.cloud import storage

    client = storage.Client()
    src_bucket_name, src_prefix = split_gs_uri(source_uri)
    dst_bucket_name, dst_prefix = split_gs_uri(target_uri)
    dst_bucket = client.bucket(dst_bucket_name)

    copied = 0
    for blob in client.list_blobs(src_bucket_name, prefix=f"{src_prefix}/"):
        relative = blob.name[len(src_prefix) + 1 :]
        if not dry_run:
            target = dst_bucket.blob(f"{dst_prefix}/{relative}")
            token, _, _ = target.rewrite(blob)
            while token is not None:
                token, _, _ = target.rewrite(blob, token=token)
        copied += 1
    return copied


def _already_migrated(client: Any, experiment_id: str, run_id: str) -> bool:
    """Return whether ``run_id`` was already copied into ``experiment_id``."""
    from mlflow.entities import ViewType

    found = client.search_runs(
        [experiment_id],
        filter_string=f"tags.{MIGRATED_FROM_RUN_ID} = '{run_id}'",
        run_view_type=ViewType.ALL,
        max_results=1,
    )
    return bool(found)


def migrate_run(
    source: Any,
    target: Any,
    run: Any,
    target_experiment_id: str | None,
    *,
    copy: bool,
    dry_run: bool,
) -> None:
    """Copy one run's metadata, and optionally its artifacts, to the server.

    Args:
        source: ``MlflowClient`` on the file store.
        target: ``MlflowClient`` on the server.
        run: The source ``mlflow.entities.Run``.
        target_experiment_id: Experiment id on the server; ``None`` only in
            a dry run, before the experiment exists.
        copy: Copy artifacts inside GCS.
        dry_run: Log what would happen and change nothing.
    """
    from mlflow.entities import Metric, Param

    info = run.info
    metric_history = [
        metric
        for key in run.data.metrics
        for metric in source.get_metric_history(info.run_id, key)
    ]
    status, status_changed = terminal_status(info.status)
    logger.info(
        "Run %s (%s): %d params, %d metric points, status %s%s",
        info.run_id,
        info.run_name,
        len(run.data.params),
        len(metric_history),
        info.status,
        f" -> {status}" if status_changed else "",
    )
    if dry_run:
        if copy and info.artifact_uri.startswith("gs://"):
            count = copy_artifacts(info.artifact_uri, info.artifact_uri, dry_run=True)
            logger.info("  would copy %d artifact objects", count)
        return

    tags = {**run.data.tags, MIGRATED_FROM_ARTIFACT_URI: info.artifact_uri}
    if status_changed:
        tags[MIGRATED_FROM_STATUS] = info.status
    created = target.create_run(
        target_experiment_id,
        start_time=info.start_time,
        tags=tags,
        run_name=info.run_name,
    )
    new_id = created.info.run_id

    # The migrated_from_run_id marker is what a re-run skips on, so it is
    # set last: a copy that fails halfway is deleted and has no marker, and
    # the next run starts that run over.
    try:
        params = [Param(key, value) for key, value in run.data.params.items()]
        for batch in chunked(params, MAX_PARAMS_PER_BATCH):
            target.log_batch(new_id, params=batch)
        metrics = [Metric(m.key, m.value, m.timestamp, m.step) for m in metric_history]
        for batch in chunked(metrics, MAX_METRICS_PER_BATCH):
            target.log_batch(new_id, metrics=batch)

        if copy:
            if info.artifact_uri.startswith("gs://"):
                count = copy_artifacts(
                    info.artifact_uri, created.info.artifact_uri, dry_run=False
                )
                logger.info("  copied %d artifact objects", count)
            else:
                logger.warning(
                    "  artifacts at %s are not in GCS; not copied", info.artifact_uri
                )

        target.set_terminated(new_id, status=status, end_time=info.end_time)
        target.set_tag(new_id, MIGRATED_FROM_RUN_ID, info.run_id)
    except Exception:
        logger.error(
            "  copy of %s failed; deleting partial run %s", info.run_id, new_id
        )
        target.delete_run(new_id)
        raise

    if info.lifecycle_stage == "deleted":
        target.delete_run(new_id)
    logger.info("  -> %s", new_id)


def migrate(source_dir: Path, *, copy: bool, dry_run: bool) -> int:
    """Copy every experiment and run from a file store to the server.

    Args:
        source_dir: The file store directory (``mlruns``).
        copy: Copy artifacts inside GCS.
        dry_run: Log what would happen and change nothing.

    Returns:
        Number of runs copied (or that would be).
    """
    from mlflow.entities import ViewType
    from mlflow.tracking import MlflowClient

    # MLflow 3 refuses to open a file store unless told to; reading one out
    # is the whole job here.
    os.environ.setdefault("MLFLOW_ALLOW_FILE_STORE", "true")
    source = MlflowClient(tracking_uri=source_dir.resolve().as_uri())
    target = MlflowClient()

    registered = source.search_registered_models()
    if registered:
        logger.warning(
            "%d registered models in the file store are not migrated: %s",
            len(registered),
            ", ".join(model.name for model in registered),
        )

    migrated = 0
    for experiment in source.search_experiments(view_type=ViewType.ALL):
        runs = source.search_runs(
            [experiment.experiment_id], run_view_type=ViewType.ALL
        )
        if not runs:
            continue
        logger.info("Experiment %s: %d runs", experiment.name, len(runs))

        existing = target.get_experiment_by_name(experiment.name)
        if existing is not None:
            target_id = existing.experiment_id
        elif dry_run:
            target_id = None
        else:
            target_id = target.create_experiment(experiment.name)

        for run in runs:
            if target_id is not None and _already_migrated(
                target, target_id, run.info.run_id
            ):
                logger.info("Run %s already migrated; skipped", run.info.run_id)
                continue
            migrate_run(source, target, run, target_id, copy=copy, dry_run=dry_run)
            migrated += 1
    return migrated


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments.

    Args:
        argv: Argument list; ``None`` reads ``sys.argv``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("/home/jupyter/mlruns"),
        help="File store directory to copy from.",
    )
    parser.add_argument(
        "--no-copy-artifacts",
        dest="copy",
        action="store_false",
        help="Do not copy artifacts; the tag still points at the originals.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Log what would be copied and change nothing.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point.

    Args:
        argv: Argument list; ``None`` reads ``sys.argv``.

    Returns:
        Process exit code.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)

    if not os.environ.get("MLFLOW_TRACKING_URI", "").startswith("https://"):
        logger.error("Set MLFLOW_TRACKING_URI to the MLflow server's https:// URL.")
        return 2
    audience = os.environ.get(IAP_AUDIENCE_ENV)
    if not audience:
        logger.error("Set %s to the IAP OAuth client ID.", IAP_AUDIENCE_ENV)
        return 2
    if not args.source.is_dir():
        logger.error("No file store at %s.", args.source)
        return 2

    use_iap_token(audience)
    count = migrate(args.source, copy=args.copy, dry_run=args.dry_run)
    logger.info("%s %d runs.", "Would migrate" if args.dry_run else "Migrated", count)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
