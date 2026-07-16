"""GCS raw archive -> BigQuery staging load step.

Two deterministic stages, both idempotent:

1. A native BigQuery load job truncate-loads every ``*.jsonl.gz`` object
   from the raw archive into the permanent ``raw_landing`` table, so each
   load reflects exactly the current bucket contents.
2. A ``MERGE`` deduplicates the landing rows by ``id`` (freshest
   ``collected_at`` wins) into ``raw_staging`` — re-running the load
   against unchanged data is a no-op.

Runnable locally with application-default credentials::

    python -m publisher.load
"""

from __future__ import annotations

import logging

from google.cloud import bigquery

from publisher.config import RunConfig, load_config

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("publisher.load")

# All record fields, in schema order. Shared by the MERGE column lists.
_RECORD_FIELDS = (
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


def landing_source_uri(bucket: str) -> str:
    """Return the GCS source URI pattern covering every raw archive object.

    BigQuery's ``*`` wildcard matches across ``/`` (GCS has a flat
    namespace), so one trailing wildcard covers the nested
    ``{source}/{event}/{YYYY}/{MM}/{DD}/{HH}/`` prefixes the collectors
    write under.

    Args:
        bucket: Raw archive bucket name.

    Returns:
        A ``gs://`` URI with a wildcard object pattern.
    """
    return f"gs://{bucket}/*.jsonl.gz"


def build_merge_sql(project: str, dataset: str, landing: str, staging: str) -> str:
    """Build the dedup MERGE from the landing table into staging.

    Dedup semantics: within one load, keep the row with the latest
    ``collected_at`` per ``id``; across loads, only overwrite a staging
    row when the incoming copy is fresher. Re-running the load is a
    no-op. The match on ``id`` has no partition predicate — a full scan
    of staging that is fine at this dataset's scale.

    Args:
        project: GCP project id.
        dataset: Short BigQuery dataset id.
        landing: Short landing table id.
        staging: Short staging table id.

    Returns:
        The MERGE statement as a string (identifiers interpolated, no
        values — there is no user input here).
    """
    update_assignments = ",\n      ".join(
        f"{field} = s.{field}" for field in _RECORD_FIELDS if field != "id"
    )
    return f"""
    MERGE `{project}.{dataset}.{staging}` AS t
    USING (
      SELECT * EXCEPT (rn)
      FROM (
        SELECT
          *,
          ROW_NUMBER() OVER (PARTITION BY id ORDER BY collected_at DESC) AS rn
        FROM `{project}.{dataset}.{landing}`
      )
      WHERE rn = 1
    ) AS s
    ON t.id = s.id
    WHEN MATCHED AND s.collected_at > t.collected_at THEN UPDATE SET
      {update_assignments}
    WHEN NOT MATCHED THEN
      INSERT ROW
    """


def run_load(config: RunConfig, client: bigquery.Client) -> tuple[int, int]:
    """Load the raw archive into landing, then MERGE into staging.

    The load job takes its schema from the Terraform-managed landing
    table — autodetect stays off so schema drift fails loudly instead of
    silently reshaping the table.

    Args:
        config: The active run configuration.
        client: An authenticated BigQuery client.

    Returns:
        A ``(landing_rows, staging_rows)`` tuple of post-load row counts.
    """
    uri = landing_source_uri(config.raw_archive_bucket)
    landing_ref = f"{config.project_id}.{config.bq_dataset}.{config.bq_landing_table}"
    staging_ref = f"{config.project_id}.{config.bq_dataset}.{config.bq_staging_table}"

    logger.info("Loading %s into %s (WRITE_TRUNCATE)", uri, landing_ref)
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_uri(uri, landing_ref, job_config=job_config).result()
    landing_rows = int(client.get_table(landing_ref).num_rows)
    logger.info("Landing table %s now holds %d rows.", landing_ref, landing_rows)

    merge_sql = build_merge_sql(
        config.project_id,
        config.bq_dataset,
        config.bq_landing_table,
        config.bq_staging_table,
    )
    logger.info("Merging deduplicated landing rows into %s", staging_ref)
    client.query(merge_sql).result()
    staging_rows = int(client.get_table(staging_ref).num_rows)
    logger.info("Staging table %s now holds %d rows.", staging_ref, staging_rows)

    return landing_rows, staging_rows


def main() -> None:
    """Run the load step standalone (local entry point)."""
    config = load_config()
    client = bigquery.Client(project=config.project_id)
    landing_rows, staging_rows = run_load(config, client)
    logger.info(
        "Load finished: %d landing rows, %d staging rows.",
        landing_rows,
        staging_rows,
    )


if __name__ == "__main__":
    main()
