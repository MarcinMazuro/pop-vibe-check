# ----------------------------------------------------------------------------
# Dataflow module — IAM and launch parameters for the streaming pipeline.
#
# This module owns what is genuinely Dataflow-specific and does not belong
# to the network / storage / pubsub / bigquery modules that provision the
# resources the job touches:
#
#   - the worker SA's project-scope roles/dataflow.worker grant;
#   - the launcher's roles/dataflow.admin and actAs-worker grants;
#   - the composed set of launch parameters PR 3 reads from terraform output.
#
# Deliberately NO google_dataflow_flex_template_job resource here — see the
# block comment on that decision below. A streaming Dataflow job is the
# single most expensive thing in this project, and `terraform apply` must
# never be the thing that starts one.
# ----------------------------------------------------------------------------

# ----------------------------------------------------------------------------
# Worker SA — the identity the job's VMs run as.
#
# roles/dataflow.worker is the standard project-scope grant that lets a SA
# act as a Dataflow worker (poll work, report status, run the harness). The
# worker's rights on the actual data — Pub/Sub subscribe, BigQuery write,
# GCS staging, Artifact Registry pull — are granted in those resources'
# modules, next to what they protect.
# ----------------------------------------------------------------------------
resource "google_project_iam_member" "worker" {
  project = var.project_id
  role    = "roles/dataflow.worker"
  member  = "serviceAccount:${var.dataflow_worker_sa_email}"
}

# ----------------------------------------------------------------------------
# Launcher — the principal that submits the Flex Template job.
#
# Two grants, both required to launch a job that runs as a *different*
# identity (the worker SA):
#   - roles/dataflow.admin at project scope: create and manage jobs.
#   - roles/iam.serviceAccountUser on the worker SA: "actAs" it, i.e.
#     submit a job that assumes the worker SA. Without this, the launch is
#     rejected with a serviceAccounts.actAs permission error.
#
# The worker SA is created in the iam module; the actAs binding is
# addressed here by its email (service_account_id accepts the
# projects/-/serviceAccounts/<email> form) so this module doesn't need the
# SA resource itself.
# ----------------------------------------------------------------------------
resource "google_project_iam_member" "launcher_admin" {
  project = var.project_id
  role    = "roles/dataflow.admin"
  member  = "serviceAccount:${var.launcher_sa_email}"
}

resource "google_service_account_iam_member" "launcher_act_as_worker" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${var.dataflow_worker_sa_email}"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.launcher_sa_email}"
}

# ----------------------------------------------------------------------------
# NO google_dataflow_flex_template_job here — on purpose.
#
# Two reasons. First, there is no template to point one at yet: the Flex
# Template image and spec are built in PR 3. Second and more important, a
# streaming Dataflow job runs (and bills) continuously until drained, so
# having `terraform apply` create it would make routine applies start the
# most expensive resource in the project — exactly the accident this whole
# PR is structured to prevent.
#
# The launch therefore stays out of Terraform for now: PR 3 runs
# `gcloud dataflow flex-template run` (or decides to add a gated resource
# then) using the parameters this module outputs. If a resource is ever
# added, gate it on a variable defaulting to null so it is count = 0 until
# an operator opts in, the same way cloud_run_jobs keeps reddit_image_uri
# on a placeholder until a real image exists. See this module's README.
# ----------------------------------------------------------------------------

locals {
  # Launch locations composed from the dataflow-temp bucket. staging/ and
  # temp/ are swept by the bucket lifecycle rule after 7 days; templates/
  # is exempt (it holds the spec every launch reads).
  temp_location     = "${var.dataflow_temp_bucket_url}/temp"
  staging_location  = "${var.dataflow_temp_bucket_url}/staging"
  template_spec_dir = "${var.dataflow_temp_bucket_url}/templates"

  # BigQuery table refs in PROJECT:DATASET.TABLE form (the classic BigQuery
  # table reference the Beam BigQueryIO sink accepts).
  events_landing_table = "${var.project_id}:${var.bq_dataset_id}.${var.events_landing_table_id}"
  events_table         = "${var.project_id}:${var.bq_dataset_id}.${var.events_table_id}"
}
