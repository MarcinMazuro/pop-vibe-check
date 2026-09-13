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
