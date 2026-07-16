"""Environment-driven configuration for the replay publisher.

All runtime configuration comes from environment variables, matching the
collector convention: deploy-time literals are baked into the Cloud Run
Job template, execution-time parameters (``RUN_LOAD``, ``EVENT_ID``,
``WINDOW_FROM``, ``WINDOW_TO`` and pacing overrides) are supplied per run
via ``gcloud run jobs execute --update-env-vars``. Configuration errors
fail loudly at startup rather than mid-replay.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import UTC, datetime

from collectors.common.events_config import resolve_event

# Valid values for the RUN_LOAD execution-time parameter:
# - "false": replay only (staging already populated) — the default.
# - "true":  load GCS -> landing -> MERGE -> staging, then replay.
# - "only":  load, then exit without replaying ("prepare data" run).
RUN_LOAD_CHOICES = ("false", "true", "only")

# Pub/Sub ordering guarantees require publishing through the regional
# endpoint of the topic's region. Overridable for tests via the
# PUBSUB_ENDPOINT env var.
DEFAULT_PUBSUB_ENDPOINT = "europe-central2-pubsub.googleapis.com:443"


@dataclass(frozen=True)
class RunConfig:
    """Resolved configuration for a single publisher run.

    Attributes:
        project_id: GCP project the BigQuery jobs and Pub/Sub topic live in.
        bq_dataset: Short BigQuery dataset id (e.g. ``co_analytics_dev``).
        bq_landing_table: Short table id of the truncate-and-load landing
            table.
        bq_staging_table: Short table id of the deduplicated staging table
            the replay reads from.
        raw_archive_bucket: Name of the GCS raw archive bucket the load
            step reads.
        pubsub_topic: Short name of the Pub/Sub topic to replay into.
        pubsub_endpoint: Regional Pub/Sub API endpoint (ordering requires
            the topic's regional endpoint).
        speedup: Time-compression factor — real inter-record gaps are
            divided by this before sleeping.
        max_sleep_seconds: Upper clamp on any single inter-record sleep,
            so months of dead air between lifecycle events are skipped.
        run_load: One of :data:`RUN_LOAD_CHOICES`.
        event_id: Optional lifecycle event filter for the replay.
        window_from: Optional inclusive lower bound on ``created_utc``.
        window_to: Optional exclusive upper bound on ``created_utc``.
    """

    project_id: str
    bq_dataset: str
    bq_landing_table: str
    bq_staging_table: str
    raw_archive_bucket: str
    pubsub_topic: str
    pubsub_endpoint: str
    speedup: float
    max_sleep_seconds: float
    run_load: str
    event_id: str | None
    window_from: datetime | None
    window_to: datetime | None


def _require_env(name: str) -> str:
    """Return a required environment variable or fail loudly.

    Args:
        name: Environment variable name.

    Returns:
        The variable's value.

    Raises:
        ValueError: If the variable is unset or empty.
    """
    value = os.environ.get(name)
    if not value:
        raise ValueError(f"Required environment variable {name} is unset or empty.")
    return value


def _parse_iso_utc(value: str) -> datetime:
    """Parse an ISO 8601 timestamp into a timezone-aware UTC datetime.

    Args:
        value: ISO 8601 string, with optional trailing ``Z``.

    Returns:
        A timezone-aware :class:`datetime` in UTC.
    """
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _optional_iso_utc(name: str) -> datetime | None:
    """Parse an optional ISO 8601 env var into a UTC datetime.

    Args:
        name: Environment variable name.

    Returns:
        The parsed datetime, or ``None`` when the variable is unset/empty.
    """
    value = os.environ.get(name)
    if not value:
        return None
    return _parse_iso_utc(value)


def load_config() -> RunConfig:
    """Build the run configuration from environment variables.

    ``SPEEDUP`` and ``MAX_SLEEP_SECONDS`` default to the values baked into
    the Cloud Run Job template so local runs behave like deployed ones.

    Returns:
        The resolved :class:`RunConfig`.

    Raises:
        ValueError: If a required variable is missing or a value is invalid.
        KeyError: If ``EVENT_ID`` is set but unknown.
    """
    speedup = float(os.environ.get("SPEEDUP") or "86400")
    if speedup <= 0:
        raise ValueError(f"SPEEDUP must be positive, got {speedup}.")

    max_sleep_seconds = float(os.environ.get("MAX_SLEEP_SECONDS") or "5")
    if max_sleep_seconds < 0:
        raise ValueError(
            f"MAX_SLEEP_SECONDS must be non-negative, got {max_sleep_seconds}."
        )

    run_load = (os.environ.get("RUN_LOAD") or "false").lower()
    if run_load not in RUN_LOAD_CHOICES:
        raise ValueError(
            f"RUN_LOAD must be one of {RUN_LOAD_CHOICES}, got '{run_load}'."
        )

    event_id = os.environ.get("EVENT_ID") or None
    if event_id is not None:
        resolve_event(event_id)  # Fail loudly on an unknown event id.

    window_from = _optional_iso_utc("WINDOW_FROM")
    window_to = _optional_iso_utc("WINDOW_TO")
    if window_from is not None and window_to is not None and window_from >= window_to:
        raise ValueError(
            f"WINDOW_FROM ({window_from.isoformat()}) must be earlier than "
            f"WINDOW_TO ({window_to.isoformat()})."
        )

    return RunConfig(
        project_id=_require_env("PROJECT_ID"),
        bq_dataset=_require_env("BQ_DATASET"),
        bq_landing_table=_require_env("BQ_LANDING_TABLE"),
        bq_staging_table=_require_env("BQ_STAGING_TABLE"),
        raw_archive_bucket=_require_env("RAW_ARCHIVE_BUCKET"),
        pubsub_topic=_require_env("PUBSUB_TOPIC"),
        pubsub_endpoint=os.environ.get("PUBSUB_ENDPOINT") or DEFAULT_PUBSUB_ENDPOINT,
        speedup=speedup,
        max_sleep_seconds=max_sleep_seconds,
        run_load=run_load,
        event_id=event_id,
        window_from=window_from,
        window_to=window_to,
    )
