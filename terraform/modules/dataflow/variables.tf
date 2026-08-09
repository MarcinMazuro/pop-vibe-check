variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "region" {
  description = "Region the Dataflow job runs in. Project standard is europe-central2."
  type        = string
}

# --- Identities -------------------------------------------------------------

variable "dataflow_worker_sa_email" {
  description = "Email of the Dataflow worker SA — granted roles/dataflow.worker at project scope and set as the actAs target for the launcher."
  type        = string
}

variable "launcher_sa_email" {
  description = <<-EOT
    Email of the principal that launches Dataflow Flex Template jobs
    (e.g. the Cloud Build SA, or an operator impersonating it). Granted
    roles/dataflow.admin at project scope and roles/iam.serviceAccountUser
    on the worker SA so it can submit a job that runs as the worker SA.
  EOT
  type        = string
}

# --- Launch-parameter pass-through ------------------------------------------
# These are echoed back out as the launch parameters PR 3's
# `gcloud dataflow flex-template run` reads from `terraform output`, so the
# invocation never hardcodes a self-link, bucket path, or table ref.

variable "subnetwork_self_link" {
  description = "Self-link of the subnet the workers run in. Passed to the launch as --subnetwork."
  type        = string
}

variable "network_self_link" {
  description = "Self-link of the VPC the workers run in. Informational; --subnetwork alone is enough for a regional launch."
  type        = string
}

variable "worker_network_tag" {
  description = "Network tag the inter-worker firewall rule targets (Dataflow auto-applies it to worker VMs). Echoed for documentation/verification."
  type        = string
}

variable "dataflow_temp_bucket_url" {
  description = "gs:// URL of the dataflow-temp bucket. temp/staging/template locations are composed from it."
  type        = string
}

variable "bq_dataset_id" {
  description = "Short BigQuery dataset id (e.g. 'co_analytics_dev'). Used to compose the events / events_landing table refs."
  type        = string
}

variable "events_landing_table_id" {
  description = "Short table id of the Dataflow write target (e.g. 'events_landing')."
  type        = string
}

variable "events_table_id" {
  description = "Short table id of the analytical events table (e.g. 'events'). MERGE target, not a Dataflow write target."
  type        = string
}

variable "dataflow_subscription_id" {
  description = "Fully-qualified Pub/Sub subscription resource ID the pipeline consumes (projects/.../subscriptions/...)."
  type        = string
}

variable "dlq_topic_id" {
  description = "Fully-qualified dead-letter topic resource ID the pipeline publishes unparseable records to (projects/.../topics/...)."
  type        = string
}
