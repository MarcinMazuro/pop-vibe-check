"""Load generator: publish staged records as fast as asked, without ordering.

The replay publisher is built for faithful replays: one global ordering
key and a wait for every publish, which keeps chronology exact and caps it
at roughly 50 messages per second (E1 measured exactly that). Capacity
experiments need more load than that, and do not need order, so this
generator publishes the same messages — built by the publisher's own
``build_message`` from the same staging rows — with batching and no
ordering key, optionally paced to a target rate.

It runs on the operator's machine with application-default credentials.
Use it through ``perf/run.py --load-source loadgen``, which starts it once
the experiment's Dataflow job is running and cleans up after a failure.

DANGER when run on its own: the subscription is shared with real replays.
Messages published while no experiment job is consuming them stay in the
subscription, and the next real replay would write them into
events_landing and promote them into events. The standalone CLI therefore
refuses to run without ``--yes``; purge the subscription afterwards
(``gcloud pubsub subscriptions seek SUB --time=$(date -u +%FT%TZ)``) if
nothing consumed what it sent.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from perf.experiment import ALLOWED_STAGING_TABLES, PERF_STAGING_TABLE

PROGRESS_SECONDS = 10.0


class Pacer:
    """Spaces calls to at most ``rate`` per second (no limit when ``None``).

    A token bucket of one second's worth of tokens: short stalls (a slow
    BigQuery page, a GC pause) are caught up without exceeding the rate
    over any one-second span.
    """

    def __init__(
        self,
        rate: float | None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Create a pacer.

        Args:
            rate: Target calls per second; ``None`` for no limit.
            clock: Monotonic clock in seconds (injectable for tests).
            sleep: Sleep function (injectable for tests).

        Raises:
            ValueError: If ``rate`` is not positive.
        """
        if rate is not None and rate <= 0:
            raise ValueError("rate must be positive.")
        self._rate = rate
        self._clock = clock
        self._sleep = sleep
        self._capacity = max(rate or 0.0, 1.0)
        self._tokens = self._capacity
        self._last = clock()

    def wait(self) -> None:
        """Block until the next call is allowed."""
        if self._rate is None:
            return
        now = self._clock()
        self._tokens = min(
            self._capacity, self._tokens + (now - self._last) * self._rate
        )
        self._last = now
        if self._tokens < 1.0:
            delay = (1.0 - self._tokens) / self._rate
            self._sleep(delay)
            self._last = self._clock()
            self._tokens = 0.0
        else:
            self._tokens -= 1.0


@dataclass(frozen=True)
class LoadSummary:
    """Outcome of one load-generation run."""

    published: int
    failed: int
    seconds: float
    mean_rps: float
    peak_rps: int
    target_rps: float | None


def summarize(
    per_second: Iterable[int],
    published: int,
    failed: int,
    seconds: float,
    target_rps: float | None,
) -> LoadSummary:
    """Summarise a run from its per-second publish counts.

    Args:
        per_second: Messages accepted by Pub/Sub in each wall-clock second.
        published: Messages accepted in total.
        failed: Messages whose publish failed.
        seconds: Wall-clock duration of the publishing loop.
        target_rps: The requested rate, if any.

    Returns:
        The run summary.
    """
    counts = list(per_second)
    return LoadSummary(
        published=published,
        failed=failed,
        seconds=round(seconds, 1),
        mean_rps=round(published / seconds, 1) if seconds > 0 else 0.0,
        peak_rps=max(counts, default=0),
        target_rps=target_rps,
    )


def topic_for_subscription(subscription: str) -> str:
    """Return the topic a subscription is attached to."""
    from perf import gcp

    return gcp.run_text(
        [
            "gcloud",
            "pubsub",
            "subscriptions",
            "describe",
            subscription,
            "--format=value(topic)",
        ]
    )


def generate(
    project: str,
    dataset: str,
    staging_table: str,
    topic_path: str,
    rate: float | None = None,
) -> LoadSummary:
    """Publish every record of a staging table to the pipeline's topic.

    Args:
        project: GCP project id.
        dataset: Analytics dataset id.
        staging_table: ``raw_staging`` or ``raw_staging_perf``.
        topic_path: ``projects/…/topics/…`` the pipeline subscribes to.
        rate: Target messages per second; ``None`` publishes flat out.

    Returns:
        What was published, and how fast.

    Raises:
        ValueError: If the staging table is not an allowed one.
        RuntimeError: If any publish failed.
    """
    if staging_table not in ALLOWED_STAGING_TABLES:
        raise ValueError(f"staging_table must be one of {ALLOWED_STAGING_TABLES}.")

    from google.cloud import bigquery
    from google.cloud.pubsub_v1 import PublisherClient
    from google.cloud.pubsub_v1.types import (
        BatchSettings,
        LimitExceededBehavior,
        PublisherOptions,
        PublishFlowControl,
    )
    from publisher.config import DEFAULT_PUBSUB_ENDPOINT
    from publisher.replay import build_message, build_replay_query

    publisher = PublisherClient(
        batch_settings=BatchSettings(
            max_messages=500, max_bytes=4 * 1024 * 1024, max_latency=0.05
        ),
        publisher_options=PublisherOptions(
            flow_control=PublishFlowControl(
                message_limit=20_000,
                byte_limit=64 * 1024 * 1024,
                limit_exceeded_behavior=LimitExceededBehavior.BLOCK,
            )
        ),
        client_options={"api_endpoint": DEFAULT_PUBSUB_ENDPOINT},
    )
    bq = bigquery.Client(project=project)
    sql, params = build_replay_query(project, dataset, staging_table)
    rows = bq.query(
        sql, job_config=bigquery.QueryJobConfig(query_parameters=params)
    ).result(page_size=10_000)
    expected = rows.total_rows or 0
    print(f"Publishing {expected} records from {staging_table} to {topic_path}")

    pacer = Pacer(rate)
    state: dict[str, Any] = {"ok": 0, "failed": 0, "per_second": {}}
    lock = threading.Lock()  # callbacks run on the client's worker threads
    start = time.monotonic()

    def done(future: Any) -> None:
        second = int(time.monotonic() - start)
        failed = future.exception() is not None
        with lock:
            if failed:
                state["failed"] += 1
            else:
                state["ok"] += 1
                state["per_second"][second] = state["per_second"].get(second, 0) + 1

    futures = []
    last_report = start
    sent = 0
    replayed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    for row in rows:
        pacer.wait()
        data, attributes = build_message(dict(row), replayed_at=replayed_at)
        future = publisher.publish(topic_path, data, **attributes)
        future.add_done_callback(done)
        futures.append(future)
        sent += 1
        now = time.monotonic()
        if now - last_report >= PROGRESS_SECONDS:
            elapsed = now - start
            print(
                f"  {elapsed:6.0f}s sent {sent}/{expected} "
                f"({sent / elapsed:.0f}/s), confirmed {state['ok']}"
            )
            last_report = now

    for future in futures:
        try:
            future.result(timeout=300)
        except Exception:  # counted by the callback
            pass
    seconds = time.monotonic() - start

    summary = summarize(
        state["per_second"].values(), state["ok"], state["failed"], seconds, rate
    )
    print(
        f"Published {summary.published} in {summary.seconds}s: "
        f"mean {summary.mean_rps}/s, peak {summary.peak_rps}/s, "
        f"failed {summary.failed}"
    )
    if summary.failed:
        raise RuntimeError(f"{summary.failed} messages failed to publish.")
    return summary


def main(argv: list[str] | None = None) -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description="Publish staged records fast.")
    parser.add_argument(
        "--staging-table", choices=ALLOWED_STAGING_TABLES, default=PERF_STAGING_TABLE
    )
    parser.add_argument("--rate", type=float, help="Messages per second (no limit).")
    parser.add_argument("--dataset", default="co_analytics_dev")
    parser.add_argument(
        "--subscription",
        default="co-events-dataflow-sub-dev",
        help="Pipeline subscription; its topic is the target.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm an experiment job is running to consume the messages.",
    )
    args = parser.parse_args(argv)
    if not args.yes:
        print(
            "Refusing: messages published with no experiment job consuming them "
            "would leak into the next real replay. Use perf/run.py "
            "--load-source loadgen, or pass --yes while a perf job is running.",
            file=sys.stderr,
        )
        return 2

    from perf import gcp

    project = gcp.current_project()
    topic = topic_for_subscription(args.subscription)
    summary = generate(project, args.dataset, args.staging_table, topic, args.rate)
    print(asdict(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
