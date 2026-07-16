# ----------------------------------------------------------------------------
# Workload service accounts (Phase 0).
#
# One SA per workload — never shared. Each SA is created here as a bare
# identity; resource-level IAM bindings (objectAdmin on raw archive,
# secretAccessor on Reddit/YouTube creds, writer on Artifact Registry, etc.)
# live in the modules that own those resources, per the convention in this
# project's IaC guidelines.
#
# The Dataflow worker SA is deferred to the Dataflow PR.
#
# google_service_account does not support labels in provider v5 — there is
# nothing to tag here even though every other resource gets the standard
# label set.
# ----------------------------------------------------------------------------
locals {
  workloads = {
    "collector-reddit" = {
      display_name = "Reddit collector"
      description  = "Reads the Reddit API and writes raw JSONL to the raw archive bucket. Run as the reddit-collector Cloud Run Job."
    }
    "collector-youtube" = {
      display_name = "YouTube collector"
      description  = "Reads the YouTube Data API and writes raw JSONL to the raw archive bucket. Run as the youtube-collector Cloud Run Job."
    }
    "publisher" = {
      display_name = "Replay publisher"
      description  = "Loads the GCS raw archive into BigQuery staging and replays it chronologically to Pub/Sub with time compression. Run as the publisher Cloud Run Job."
    }
    "cloud-build" = {
      display_name = "Cloud Build runner"
      description  = "Executes Cloud Build triggers for this environment — terraform plans, collector image builds, publisher image builds, Dataflow Flex Template uploads. Per-env so dev cannot push to prod artifact registry."
    }
  }
}

resource "google_service_account" "workload" {
  for_each = local.workloads

  project      = var.project_id
  account_id   = "${var.name_prefix}-${each.key}-sa-${var.env}"
  display_name = each.value.display_name
  description  = each.value.description
}
