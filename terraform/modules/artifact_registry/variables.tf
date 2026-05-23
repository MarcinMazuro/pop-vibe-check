variable "project_id" {
  description = "GCP project ID — used in the repository URL output."
  type        = string
}

variable "name_prefix" {
  description = "Short release prefix prepended to the repository ID (e.g. 'co' for Clair Obscur)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", var.name_prefix)) && length(var.name_prefix) <= 8
    error_message = "name_prefix must be 2-8 chars, lowercase alphanumeric or hyphen, start with a letter, end alphanumeric."
  }
}

variable "env" {
  description = "Environment name (e.g. 'dev', 'prod'). Suffixed into the repository ID."
  type        = string
}

variable "region" {
  description = "GCP region for the Artifact Registry repository. Project standard is europe-central2."
  type        = string
}

variable "labels" {
  description = "Labels applied to the repository."
  type        = map(string)
}

variable "writer_sa_emails" {
  description = "List of SA emails granted roles/artifactregistry.writer — typically just the per-env Cloud Build SA. Pass as a list rather than a single value so the API generalises cleanly when a second pusher (e.g. a release-promotion job) is added."
  type        = list(string)
}

variable "reader_sa_emails" {
  description = "List of SA emails granted roles/artifactregistry.reader. Workloads that pull images from the repository at runtime (collector and publisher Cloud Run Jobs, Dataflow workers)."
  type        = list(string)
}
