variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "name_prefix" {
  description = "Short release prefix (e.g. 'co') prepended to secret, connection and trigger names."
  type        = string
}

variable "env" {
  description = "Environment name (e.g. 'dev'). Suffixed into every name."
  type        = string
}

variable "region" {
  description = "Region for the connection, repository and triggers. Builds run in the regional default pool here."
  type        = string
}

variable "labels" {
  description = "Labels applied to the secret containers."
  type        = map(string)
}

variable "github_owner" {
  description = "GitHub user or organization that owns the repository."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name."
  type        = string
}

variable "github_app_installation_id" {
  description = "Installation ID of the Google Cloud Build GitHub App on the repository owner. null (default) creates only the secrets and grants; set it after the app is installed and the token secret has a version to create the connection, repository and triggers."
  type        = number
  default     = null
}

variable "cloud_build_sa_email" {
  description = "Per-env Cloud Build SA. Runs the Python checks and image triggers."
  type        = string
}

variable "terraform_ci_sa_email" {
  description = "Terraform CI SA from terraform/bootstrap. Runs the plan/apply triggers and reads the tfvars secret."
  type        = string
}

variable "terraform_runner_sa_email" {
  description = "Terraform runner SA the plan/apply builds impersonate for the state backend (the provider block impersonates it on its own)."
  type        = string
}

variable "terraform_env_dir" {
  description = "Repository path of the Terraform composition the plan/apply triggers run, e.g. 'terraform/envs/dev'."
  type        = string
}

variable "approver_emails" {
  description = "User emails granted roles/cloudbuild.builds.approver, i.e. allowed to release a queued terraform apply."
  type        = list(string)
  default     = []
}

variable "artifact_registry_repository_id" {
  description = "Short Artifact Registry repository ID images are pushed to (e.g. 'co-images-dev')."
  type        = string
}

variable "youtube_job_name" {
  description = "Cloud Run Job the youtube-collector image is deployed to."
  type        = string
}

variable "publisher_job_name" {
  description = "Cloud Run Job the publisher image is deployed to."
  type        = string
}

variable "template_spec_dir" {
  description = "gs:// prefix Flex Template specs are written under, e.g. 'gs://co-dataflow-temp-dev/templates'."
  type        = string
}

# --- Replay pipeline inputs -------------------------------------------------
# Everything dataflow/launch.sh and promote.sh would otherwise read from
# `terraform output`.

variable "dataflow_worker_sa_email" {
  description = "Worker SA the replayed Dataflow job runs as."
  type        = string
}

variable "dataflow_subnetwork" {
  description = "Subnetwork self-link the Dataflow workers run in."
  type        = string
}

variable "dataflow_temp_location" {
  description = "gs:// temp location for the Dataflow job."
  type        = string
}

variable "dataflow_staging_location" {
  description = "gs:// staging location for the Dataflow job."
  type        = string
}

variable "dataflow_input_subscription" {
  description = "Pub/Sub subscription the pipeline consumes."
  type        = string
}

variable "dataflow_events_landing_table" {
  description = "BigQuery write target in PROJECT:DATASET.TABLE form."
  type        = string
}

variable "dataflow_dlq_topic" {
  description = "Dead-letter topic the pipeline publishes unparseable records to."
  type        = string
}

variable "bq_dataset_id" {
  description = "Short BigQuery dataset id the replay promotes inside."
  type        = string
}

variable "raw_staging_table_id" {
  description = "Short table id of the staging table the coverage check compares against."
  type        = string
}

variable "events_landing_table_id" {
  description = "Short table id of the append-only Dataflow write target."
  type        = string
}

variable "events_table_id" {
  description = "Short table id of the analytical events table (MERGE target)."
  type        = string
}
