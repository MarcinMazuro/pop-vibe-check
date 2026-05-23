variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "name_prefix" {
  description = <<-EOT
    Short release prefix used in the dataset ID. BigQuery dataset names
    require underscores rather than hyphens, so any hyphen in name_prefix
    is converted to underscore for the dataset_id only.
  EOT
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", var.name_prefix)) && length(var.name_prefix) <= 8
    error_message = "name_prefix must be 2-8 chars, lowercase alphanumeric or hyphen, start with a letter, end alphanumeric."
  }
}

variable "env" {
  description = "Environment name (e.g. 'dev', 'prod'). Suffixed into the dataset ID."
  type        = string
}

variable "region" {
  description = "GCP region for the BigQuery dataset. Project standard is europe-central2 (regional, not multi-region)."
  type        = string
}

variable "labels" {
  description = "Labels applied to the dataset."
  type        = map(string)
}

variable "delete_contents_on_destroy" {
  description = <<-EOT
    Escape hatch for destroying the dataset when it still contains tables.
    Default false keeps the safety bar in place — a non-empty dataset
    cannot be deleted, protecting analytical data. Flip to true only via
    -var on a one-off teardown; do NOT leave true in committed code.
  EOT
  type        = bool
  default     = false
}
