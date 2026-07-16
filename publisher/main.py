"""Replay publisher entry point.

Loads configuration from the environment, optionally runs the GCS ->
BigQuery load step, then replays the staging table to Pub/Sub with time
compression.

Run as a module::

    python -m publisher.main

Configuration is taken entirely from environment variables (see the
README in this directory).
"""

from __future__ import annotations

import logging

# Module-style import: google-cloud-pubsub ships no py.typed marker, so
# the `from google.cloud import pubsub_v1` form trips mypy's attr-defined
# check (the typed bigquery package makes google.cloud resolvable).
import google.cloud.pubsub_v1 as pubsub_v1
from google.cloud import bigquery

from publisher.config import RunConfig, load_config
from publisher.load import run_load
from publisher.replay import replay

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("publisher.main")


def _build_publisher(config: RunConfig) -> pubsub_v1.PublisherClient:
    """Build a Pub/Sub publisher client with message ordering enabled.

    Ordering guarantees require both the client option below and the
    regional endpoint of the topic's region.

    Args:
        config: The active run configuration.

    Returns:
        A configured :class:`pubsub_v1.PublisherClient`.
    """
    return pubsub_v1.PublisherClient(
        publisher_options=pubsub_v1.types.PublisherOptions(
            enable_message_ordering=True
        ),
        client_options={"api_endpoint": config.pubsub_endpoint},
    )


def main() -> None:
    """Program entry point: config -> optional load -> replay -> summary."""
    config = load_config()
    logger.info(
        "Starting publisher: run_load=%s event_id=%s window=%s..%s "
        "speedup=%s max_sleep=%ss topic=%s",
        config.run_load,
        config.event_id or "<all>",
        config.window_from.isoformat() if config.window_from else "<open>",
        config.window_to.isoformat() if config.window_to else "<open>",
        config.speedup,
        config.max_sleep_seconds,
        config.pubsub_topic,
    )

    bq_client = bigquery.Client(project=config.project_id)

    if config.run_load in ("true", "only"):
        landing_rows, staging_rows = run_load(config, bq_client)
        logger.info(
            "Load finished: %d landing rows, %d staging rows.",
            landing_rows,
            staging_rows,
        )
        if config.run_load == "only":
            logger.info("RUN_LOAD=only — exiting without replay.")
            return

    publisher = _build_publisher(config)
    topic_path = publisher.topic_path(config.project_id, config.pubsub_topic)
    summary = replay(config, bq_client, publisher, topic_path)

    logger.info(
        "Replay finished: %d records published in %.1fs wall time; "
        "simulated span %s .. %s (speedup=%s, max_sleep=%ss).",
        summary.published,
        summary.wall_seconds,
        summary.first_created_utc.isoformat() if summary.first_created_utc else "-",
        summary.last_created_utc.isoformat() if summary.last_created_utc else "-",
        config.speedup,
        config.max_sleep_seconds,
    )


if __name__ == "__main__":
    main()
