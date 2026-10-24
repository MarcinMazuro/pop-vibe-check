variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "name_prefix" {
  description = "Short release prefix (e.g. 'co') prepended to the repository and secret names."
  type        = string
}

variable "env" {
  description = "Environment name (e.g. 'dev'). Suffixed into every name."
  type        = string
}

variable "region" {
  description = "Region of the Dataform repository. Kept equal to the BigQuery datasets' location (europe-central2)."
  type        = string
}

variable "labels" {
  description = "Labels applied to the repository and the token secret."
  type        = map(string)
}

variable "github_owner" {
  description = "GitHub user or organization that owns the repository."
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name. Its root holds workflow_settings.yaml, definitions/ and includes/."
  type        = string
}

variable "default_branch" {
  description = "Branch the Dataform repository compiles from and new workspaces start at."
  type        = string
  default     = "main"
}

variable "dataform_sa_email" {
  description = "Service account every workflow invocation runs as (created in the iam module). The Dataform service agent gets token-creator on it."
  type        = string
}

variable "deployer_sa_email" {
  description = "Service account that compiles and invokes the repository from Cloud Build (the per-env Cloud Build SA). Granted dataform.editor on the repository and actAs on dataform_sa_email. null skips the grants."
  type        = string
  default     = null
}

variable "editor_emails" {
  description = "User emails allowed to work in the web IDE: dataform.editor on the repository (workspaces, compile, execute) and actAs on dataform_sa_email, which an execution started from a workspace runs as."
  type        = list(string)
  default     = []
}
