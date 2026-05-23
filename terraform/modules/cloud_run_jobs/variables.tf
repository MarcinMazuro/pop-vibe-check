variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "name_prefix" {
  description = "Short release prefix prepended to job names."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", var.name_prefix)) && length(var.name_prefix) <= 8
    error_message = "name_prefix must be 2-8 chars, lowercase alphanumeric or hyphen, start with a letter, end alphanumeric."
  }
}

variable "env" {
  description = "Environment name (e.g. 'dev', 'prod'). Suffixed into job names."
  type        = string
}

variable "region" {
  description = "Region the jobs run in."
  type        = string
}

variable "labels" {
  description = "Labels applied to every job."
  type        = map(string)
}

variable "raw_archive_bucket_name" {
  description = "Name of the GCS raw archive bucket. Wired into TARGET_BUCKET env var for both collectors."
  type        = string
}

variable "reddit_collector_sa_email" {
  description = "Email of the Reddit collector SA — used as the job's runtime identity."
  type        = string
}

variable "youtube_collector_sa_email" {
  description = "Email of the YouTube collector SA — used as the job's runtime identity."
  type        = string
}

variable "secret_names" {
  description = <<-EOT
    Map of short secret name → actual secret_id (with name_prefix and env)
    produced by the secrets module. Used by secret_key_ref blocks to bind
    Reddit / YouTube credentials and the author-hash salt into the
    container as env vars at runtime — values never appear in Terraform
    state, only the reference.
  EOT
  type        = map(string)
}

variable "reddit_image_uri" {
  description = "Full image URI for the Reddit collector container. Default is the public 'pause' image; override with the Artifact Registry URI once the real image is built."
  type        = string
  default     = "gcr.io/google-containers/pause"
}

variable "youtube_image_uri" {
  description = "Full image URI for the YouTube collector container. Default is the public 'pause' image; override with the Artifact Registry URI once the real image is built."
  type        = string
  default     = "gcr.io/google-containers/pause"
}

variable "memory" {
  description = "Container memory limit per task (Cloud Run units, e.g. '2Gi')."
  type        = string
  default     = "2Gi"
}

variable "cpu" {
  description = "Container CPU limit per task (Cloud Run units, e.g. '1' or '2')."
  type        = string
  default     = "1"
}

variable "task_timeout" {
  description = "Hard timeout per task execution. 3600s (1 hour) is enough for one collection window; bump in prod if needed."
  type        = string
  default     = "3600s"
}

variable "max_retries" {
  description = "Maximum number of automatic retries per task on failure."
  type        = number
  default     = 3
}
