# ----------------------------------------------------------------------------
# Analytics dataset.
#
# Single denormalised events table + raw_staging come in Phase 1; this
# module currently only owns the dataset container so other Phase 0 work
# (storage, iam, secrets, artifact_registry, network) is fully unblocked.
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
