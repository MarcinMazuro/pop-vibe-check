# ----------------------------------------------------------------------------
# Analytics dataset.
#
# Owns the dataset container, the raw_landing / raw_staging tables the
# replay publisher uses, and the events_landing / events tables the
# Dataflow streaming pipeline writes and dedups into. Looker Studio
# authorized views land with the analytics PR.
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

  # Raw record fields — the collector output shape, mirroring
  # collectors.common.records.build_record. Only the replay-critical
  # fields are REQUIRED; the rest stay NULLABLE so a load never fails on
  # genuinely optional data (parent_id and language are nullable by
  # design, text can be empty). BigQuery's JSON loader parses the
  # collectors' ISO 8601 "...Z" strings into TIMESTAMP natively, so no
  # transform step sits between GCS and the tables.
  #
  # Held as a list (not a pre-encoded string) so events_schema below can
  # extend it instead of re-declaring eleven fields that would then be
  # free to drift out of sync with raw_landing / raw_staging.
  raw_fields = [
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
  ]

  # Shared schema string for raw_landing and raw_staging. jsonencode is
  # deterministic, so this reproduces the exact bytes the tables were
  # created with — the list refactor above is a no-op to their schema.
  raw_schema = jsonencode(local.raw_fields)

  # events / events_landing schema = the raw fields plus the four columns
  # the Dataflow pipeline adds. Two deliberate differences from the raw
  # tables, both encoded as field descriptions:
  #
  #   - language is re-described as authoritative. In raw_staging it is the
  #     collectors' advisory langdetect output, which proved unreliable on
  #     short comments (see docs/phase-0-youtube-first-collection.md); the
  #     value analysis trusts is the one Dataflow writes here. The column
  #     type/mode is unchanged, so the raw fields do not drift — only the
  #     documented meaning differs.
  #   - four enrichment columns are appended: sentiment label/score,
  #     the MLflow model version, and processed_at (the MERGE tiebreaker,
  #     see the events table below).
  events_fields = concat(
    [
      for f in local.raw_fields : (
        f.name == "language"
        ? merge(f, { description = "Authoritative language code written by the Dataflow pipeline; supersedes the advisory collector value carried in raw_staging." })
        : f.name == "collected_at"
        ? merge(f, { description = "Collector run time, carried from raw_staging. NOT the events dedup tiebreaker — that is processed_at (collected_at is identical across replays of the same staged data)." })
        : f
      )
    ],
    [
      {
        name        = "sentiment_label"
        type        = "STRING"
        mode        = "NULLABLE"
        description = "Sentiment class from the NLP model: 'pos', 'neg', or 'neu'. Written by Dataflow."
      },
      {
        name        = "sentiment_score"
        type        = "FLOAT64"
        mode        = "NULLABLE"
        description = "Model confidence for sentiment_label, 0..1. Written by Dataflow."
      },
      {
        name        = "model_version"
        type        = "STRING"
        mode        = "NULLABLE"
        description = "MLflow model version that produced the sentiment label. Written by Dataflow."
      },
      {
        name        = "processed_at"
        type        = "TIMESTAMP"
        mode        = "NULLABLE"
        description = "Dataflow-side processing time. MERGE tiebreaker into events (freshest wins); collected_at cannot serve that role because two replays over the same staged data produce identical collected_at values."
      },
    ]
  )

  events_schema = jsonencode(local.events_fields)
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
# Events landing table — the Dataflow streaming write target.
#
# Append-only and duplicate-tolerant by design: the Beam pipeline streams
# enriched rows straight in, and a run that is retried (or a replay run a
# second time) writes the same id more than once. Nothing dedups on the
# way in — the events table below is promoted from here by a post-run
# MERGE keyed on id, mirroring the raw_landing -> raw_staging split the
# publisher already uses. This keeps "same replay twice -> identical
# events" true without demanding exactly-once semantics from Pub/Sub or
# Beam (see this module's README).
#
# DAY-partitioned on created_utc so it never becomes a growing
# unpartitioned scan target. deletion_protection is off for the same
# reason as raw_landing: it holds no state of its own — it is
# regenerable by replaying the raw archive through the pipeline — and dev
# teardowns must not require console clicky-work.
# ----------------------------------------------------------------------------
resource "google_bigquery_table" "events_landing" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  table_id   = "events_landing"

  description = "Append-only Dataflow write target. May hold duplicate and multi-pass rows per id; the events table is MERGE-promoted from here (freshest processed_at wins)."

  schema = local.events_schema

  time_partitioning {
    type  = "DAY"
    field = "created_utc"
  }

  deletion_protection = false

  labels = var.labels
}

# ----------------------------------------------------------------------------
# Events table — the analytical source of truth (CLAUDE.md §9).
#
# One row per id, written only by the dedup MERGE out of events_landing
# (never by the pipeline directly). Same partition + clustering shape as
# raw_staging: DAY partition on created_utc for cost-bounded time-window
# scans, (source, event_tag) clustering for the dashboard's filter axes.
# The single denormalised table is deliberate — the dashboard layer does
# no joins.
#
# The MERGE SQL is documented in this module's README, not executed from
# Terraform: it must run *after* Dataflow has drained a replay, which
# Terraform has no way to know. deletion_protection is off, consistent
# with the rest of this module — the dataset-level
# delete_contents_on_destroy flag is the real teardown guard.
# ----------------------------------------------------------------------------
resource "google_bigquery_table" "events" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  table_id   = "events"

  description = "Analytical source of truth: one row per id, promoted from events_landing by the dedup MERGE. Partitioned by DATE(created_utc), clustered by (source, event_tag). See module README for the MERGE."

  schema = local.events_schema

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

# ----------------------------------------------------------------------------
# Dataflow worker access.
#
# Dataset-level dataEditor lets the Dataflow worker SA stream enriched
# rows into events_landing (and, if a RUN_MERGE step later runs under the
# same identity, promote them into events). jobUser is grantable only at
# project scope but exists solely for this dataset's write/MERGE jobs —
# kept here next to the data, following the publisher precedent above.
# ----------------------------------------------------------------------------
resource "google_bigquery_dataset_iam_member" "dataflow_worker_data_editor" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${var.dataflow_worker_sa_email}"
}

resource "google_project_iam_member" "dataflow_worker_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${var.dataflow_worker_sa_email}"
}

# ----------------------------------------------------------------------------
# ML trainer access (read-only).
#
# dataViewer is enough to pull gold / own-domain text out of raw_staging
# (and later events) for fine-tuning; the trainer must not write analytical
# tables. jobUser is project-scope because that is the only place it can
# be granted, and exists solely so Workbench can run SELECT jobs.
# ----------------------------------------------------------------------------
resource "google_bigquery_dataset_iam_member" "ml_trainer_data_viewer" {
  project    = var.project_id
  dataset_id = google_bigquery_dataset.analytics.dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${var.ml_trainer_sa_email}"
}

resource "google_project_iam_member" "ml_trainer_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${var.ml_trainer_sa_email}"
}
