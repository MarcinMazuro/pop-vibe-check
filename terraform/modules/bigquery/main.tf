# ----------------------------------------------------------------------------
# Analytics dataset.
#
# Owns the dataset container plus the raw_landing / raw_staging tables
# used by the replay publisher. The denormalised events table and the
# Looker Studio authorized views land with the Dataflow PR.
#
# Location is the project region (europe-central2), not a multi-region —
# multi-region BigQuery is explicitly out of scope for the thesis.
#
# Dataset IDs in BigQuery must match ^[A-Za-z0-9_]+$ (no hyphens). The
# release prefix uses hyphens elsewhere in the project, so we replace
# them with underscores for this resource only.
# ----------------------------------------------------------------------------
locals {
  dataset_id = "${replace(var.name_prefix, "-", "_")}_analytics_${var.env}"

  # Shared schema for raw_landing and raw_staging — mirrors the record
  # shape built by collectors.common.records.build_record. Only the
  # replay-critical fields are REQUIRED; the rest stay NULLABLE so a
  # load never fails on genuinely optional data (parent_id and language
  # are nullable by design, text can be empty). BigQuery's JSON loader
  # parses the collectors' ISO 8601 "...Z" strings into TIMESTAMP
  # natively, so no transform step sits between GCS and the tables.
  raw_schema = jsonencode([
    {
      name        = "id"
      type        = "STRING"
      mode        = "REQUIRED"
      description = "Source-prefixed unique id, e.g. 'youtube:Ugx...' or 'reddit:t3_...'."
    },
    {
      name        = "source"
      type        = "STRING"
      mode        = "REQUIRED"
      description = "Origin platform: 'reddit' or 'youtube'."
    },
    {
      name        = "parent_id"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Parent id for replies; NULL for top-level items."
    },
    {
      name        = "created_utc"
      type        = "TIMESTAMP"
      mode        = "REQUIRED"
      description = "Author-side creation time — the replay clock."
    },
    {
      name        = "collected_at"
      type        = "TIMESTAMP"
      mode        = "NULLABLE"
      description = "Collector run time; dedup tiebreaker (latest wins)."
    },
    {
      name        = "author_hash"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "16-char salted author hash; raw handles never stored."
    },
    {
      name        = "text"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Post or comment body."
    },
    {
      name        = "language"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Best-effort two-letter language code."
    },
    {
      name        = "score"
      type        = "INT64"
      mode        = "NULLABLE"
      description = "Reddit upvotes or YouTube like count."
    },
    {
      name        = "context_id"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Subreddit name (without r/) or YouTube video id."
    },
    {
      name        = "event_tag"
      type        = "STRING"
      mode        = "NULLABLE"
      description = "Lifecycle event id the collection run targeted."
    },
  ])
}

resource "google_bigquery_dataset" "analytics" {
  project    = var.project_id
  dataset_id = local.dataset_id
  location   = var.region

  friendly_name = "${var.name_prefix} analytics (${var.env})"
  description   = "Sentiment analytics for release ${var.name_prefix}, ${var.env} environment. Hosts raw_staging and events tables (Phase 1) plus Looker Studio authorized views."

  delete_contents_on_destroy = var.delete_contents_on_destroy

  labels = var.labels
}

# ----------------------------------------------------------------------------
# Landing table for raw archive loads.
#
# A permanent table truncated by every load (the publisher runs the BQ
# load job with WRITE_TRUNCATE), so each load deterministically reflects
# the current bucket contents and the table can be inspected between the
# load and the MERGE while debugging. Unpartitioned on purpose — it is
# rewritten wholesale and never queried by time.
#
# deletion_protection is off: the table holds no state of its own (the
# raw archive bucket is the durable copy) and dev teardowns must not
# require console clicky-work.
# ----------------------------------------------------------------------------
resource "google_bigquery_table" "raw_landing" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  table_id   = "raw_landing"

  description = "Truncate-and-load target for GCS raw archive loads. Rewritten on every load; raw_staging is the deduplicated table downstream reads."

  schema = local.raw_schema

  deletion_protection = false

  labels = var.labels
}

# ----------------------------------------------------------------------------
# Staging table — the deduplicated, chronologically queryable copy of
# the raw archive that the replay publisher reads with ORDER BY
# created_utc.
#
# Day partitioning on created_utc plus (source, event_tag) clustering is
# overkill at the current row count, but it establishes the cost-control
# pattern the thesis discusses, and the replay query's window filters
# prune on the partition column. Note the publisher's MERGE matches on
# id without a partition predicate — a full-table scan that is fine at
# this scale; revisit if the dataset grows past millions of rows.
# ----------------------------------------------------------------------------
resource "google_bigquery_table" "raw_staging" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  table_id   = "raw_staging"

  description = "Deduplicated raw records (one row per id, freshest collected_at wins). Source of truth for the replay publisher."

  schema = local.raw_schema

  time_partitioning {
    type  = "DAY"
    field = "created_utc"
  }

  clustering = ["source", "event_tag"]

  deletion_protection = false

  labels = var.labels
}

# ----------------------------------------------------------------------------
# Publisher access.
#
# Dataset-level dataEditor lets the publisher SA truncate raw_landing,
# MERGE into raw_staging, and read for replay. jobUser is only grantable
# at project scope, but it exists solely so the publisher can run its
# load/query jobs against this dataset — kept here, next to the data it
# serves, rather than in the iam module.
# ----------------------------------------------------------------------------
resource "google_bigquery_dataset_iam_member" "publisher_data_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${var.publisher_sa_email}"
}

resource "google_project_iam_member" "publisher_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${var.publisher_sa_email}"
}
