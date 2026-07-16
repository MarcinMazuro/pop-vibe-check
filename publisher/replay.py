"""Chronological Pub/Sub replay with time compression.

Reads the deduplicated staging table in ``ORDER BY created_utc, id``
order and publishes each record to the events topic, sleeping the real
inter-record gap divided by ``SPEEDUP`` (clamped to ``MAX_SLEEP_SECONDS``)
between messages. Bursts around lifecycle events keep their shape while
the months of dead air between them are skipped — the stream looks live,
just faster.

Every message is published under one constant ordering key so the global
chronological order survives Pub/Sub delivery.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from google.cloud import bigquery

from publisher.config import RunConfig

logger = logging.getLogger("publisher.replay")

# One constant ordering key for every message: Pub/Sub ordering is
# per-key, and the pipeline's hard requirement is *global* chronological
# order. The per-key throughput ceiling (1 MB/s) is orders of magnitude
# above what a paced replay produces.
ORDERING_KEY = "global"

# How many published records between progress log lines.
PROGRESS_EVERY = 200

# Bounded retry for a failed publish; after these attempts the replay
# fails loudly and the operator reruns (there is no checkpoint state).
MAX_PUBLISH_ATTEMPTS = 5

_TIMESTAMP_FIELDS = ("created_utc", "collected_at")


@dataclass(frozen=True)
class ReplaySummary:
    """Outcome of one replay run.

    Attributes:
        published: Number of records published.
        first_created_utc: ``created_utc`` of the first record, or ``None``
            when nothing matched the filters.
        last_created_utc: ``created_utc`` of the last record, or ``None``.
        wall_seconds: Wall-clock duration of the replay loop.
    """

    published: int
    first_created_utc: datetime | None
    last_created_utc: datetime | None
    wall_seconds: float


def compute_sleep_seconds(
    prev: datetime | None,
    curr: datetime,
    speedup: float,
    max_sleep: float,
) -> float:
    """Return the compressed sleep before publishing the next record.

    Args:
        prev: ``created_utc`` of the previously published record, or
            ``None`` for the first record.
        curr: ``created_utc`` of the record about to be published.
        speedup: Time-compression factor (real gap is divided by this).
        max_sleep: Upper clamp in wall seconds. Skips the months-long
            gaps between lifecycle events regardless of speedup.

    Returns:
        Sleep duration in wall seconds; ``0.0`` for the first record and
        for non-positive gaps (defensive — the ORDER BY makes negative
        gaps impossible).
    """
    if prev is None:
        return 0.0
    delta_seconds = (curr - prev).total_seconds()
    if delta_seconds <= 0:
        return 0.0
    return min(delta_seconds / speedup, max_sleep)


def build_replay_query(
    project: str,
    dataset: str,
    staging: str,
    event_id: str | None = None,
    window_from: datetime | None = None,
    window_to: datetime | None = None,
) -> tuple[str, list[bigquery.ScalarQueryParameter]]:
    """Build the parameterized replay query over the staging table.

    The ``, id`` tiebreaker makes replays byte-for-byte reproducible when
    ``created_utc`` values collide (second precision guarantees they do).
    Filter values travel as query parameters, never interpolated into the
    SQL text.

    Args:
        project: GCP project id.
        dataset: Short BigQuery dataset id.
        staging: Short staging table id.
        event_id: Optional lifecycle event filter.
        window_from: Optional inclusive lower bound on ``created_utc``.
        window_to: Optional exclusive upper bound on ``created_utc``.

    Returns:
        A ``(sql, parameters)`` tuple ready for a BigQuery query job.
    """
    field_list = ", ".join(
        (
            "id",
            "source",
            "parent_id",
            "created_utc",
            "collected_at",
            "author_hash",
            "text",
            "language",
            "score",
            "context_id",
            "event_tag",
        )
    )
    sql = f"SELECT {field_list}\nFROM `{project}.{dataset}.{staging}`\nWHERE TRUE"
    parameters: list[bigquery.ScalarQueryParameter] = []

    if event_id is not None:
        sql += "\n  AND event_tag = @event_id"
        parameters.append(bigquery.ScalarQueryParameter("event_id", "STRING", event_id))
    if window_from is not None:
        sql += "\n  AND created_utc >= @window_from"
        parameters.append(
            bigquery.ScalarQueryParameter("window_from", "TIMESTAMP", window_from)
        )
    if window_to is not None:
        sql += "\n  AND created_utc < @window_to"
        parameters.append(
            bigquery.ScalarQueryParameter("window_to", "TIMESTAMP", window_to)
        )

    sql += "\nORDER BY created_utc, id"
    return sql, parameters


def _iso_utc(moment: datetime) -> str:
    """Format a datetime in the collectors' ISO 8601 UTC shape.

    Args:
        moment: A timezone-aware datetime.

    Returns:
        An ISO 8601 string with a trailing ``Z``.
    """
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _now_iso_utc() -> str:
    """Return the current wall-clock time as an ISO 8601 UTC string.

    Returns:
        The current UTC time formatted with a trailing ``Z``.
    """
    return _iso_utc(datetime.now(UTC))


def build_message(
    record: dict[str, Any], replayed_at: str
) -> tuple[bytes, dict[str, str]]:
    """Build the Pub/Sub payload and attributes for one staged record.

    The payload is the record exactly as stored (timestamps serialized
    back to the collectors' ISO 8601 ``Z`` format) — replay metadata
    lives only in the attributes, so downstream consumers see the same
    JSON the collectors produced.

    Args:
        record: One staging row as a plain dict.
        replayed_at: Wall-clock publish time (ISO 8601 UTC).

    Returns:
        A ``(data, attributes)`` tuple: UTF-8 JSON bytes plus string
        attributes for filtering and audit (``source``, ``event_tag``,
        ``created_utc``, ``replayed_at``).
    """
    payload = dict(record)
    for field in _TIMESTAMP_FIELDS:
        value = payload.get(field)
        if isinstance(value, datetime):
            payload[field] = _iso_utc(value)

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    attributes = {
        "source": str(payload.get("source") or ""),
        "event_tag": str(payload.get("event_tag") or ""),
        "created_utc": str(payload.get("created_utc") or ""),
        "replayed_at": replayed_at,
    }
    return data, attributes


def _publish_with_retry(
    publisher: Any,
    topic_path: str,
    data: bytes,
    attributes: dict[str, str],
) -> None:
    """Publish one message, retrying transient failures with backoff.

    A failed publish pauses the ordering key inside the client, so each
    retry must call ``resume_publish`` first — which is why this is an
    explicit loop rather than a tenacity decorator.

    Args:
        publisher: A Pub/Sub publisher client with ordering enabled.
        topic_path: Fully-qualified topic path.
        data: Message payload bytes.
        attributes: Message attributes.

    Raises:
        Exception: The last publish error, after all attempts fail.
    """
    delay = 1.0
    for attempt in range(1, MAX_PUBLISH_ATTEMPTS + 1):
        future = publisher.publish(
            topic_path, data, ordering_key=ORDERING_KEY, **attributes
        )
        try:
            future.result(timeout=60)
            return
        except Exception:
            publisher.resume_publish(topic_path, ORDERING_KEY)
            if attempt == MAX_PUBLISH_ATTEMPTS:
                logger.exception(
                    "Publish failed after %d attempts; giving up.", attempt
                )
                raise
            logger.warning(
                "Publish attempt %d/%d failed; retrying in %.1fs.",
                attempt,
                MAX_PUBLISH_ATTEMPTS,
                delay,
            )
            time.sleep(delay)
            delay *= 2


def replay(
    config: RunConfig,
    bq_client: bigquery.Client,
    publisher: Any,
    topic_path: str,
) -> ReplaySummary:
    """Replay the staged records to Pub/Sub in chronological order.

    Awaiting each publish future serializes publishing, which is correct
    here: the sleep pacing already serializes the loop, and a per-record
    await surfaces publish errors at the exact record that failed.

    Args:
        config: The active run configuration.
        bq_client: An authenticated BigQuery client.
        publisher: A Pub/Sub publisher client with message ordering
            enabled, built against the regional endpoint.
        topic_path: Fully-qualified topic path to publish into.

    Returns:
        A :class:`ReplaySummary` of the run.
    """
    sql, parameters = build_replay_query(
        config.project_id,
        config.bq_dataset,
        config.bq_staging_table,
        event_id=config.event_id,
        window_from=config.window_from,
        window_to=config.window_to,
    )
    job_config = bigquery.QueryJobConfig(query_parameters=parameters)
    rows = bq_client.query(sql, job_config=job_config).result()

    started = time.monotonic()
    prev_ts: datetime | None = None
    first_ts: datetime | None = None
    published = 0

    for row in rows:
        created_utc: datetime = row["created_utc"]
        sleep_s = compute_sleep_seconds(
            prev_ts, created_utc, config.speedup, config.max_sleep_seconds
        )
        if sleep_s > 0:
            time.sleep(sleep_s)

        data, attributes = build_message(dict(row), replayed_at=_now_iso_utc())
        _publish_with_retry(publisher, topic_path, data, attributes)

        if first_ts is None:
            first_ts = created_utc
        prev_ts = created_utc
        published += 1
        if published % PROGRESS_EVERY == 0:
            logger.info(
                "Published %d records; simulated clock at %s.",
                published,
                _iso_utc(created_utc),
            )

    return ReplaySummary(
        published=published,
        first_created_utc=first_ts,
        last_created_utc=prev_ts,
        wall_seconds=time.monotonic() - started,
    )
