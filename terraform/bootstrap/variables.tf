variable "project_id" {
  description = "Target GCP project ID where bootstrap resources are created."
  type        = string
}

variable "name_prefix" {
  description = <<-EOT
    Short prefix for the universal Terraform-state bucket and runner SA.
    These are *shared* infrastructure — one bucket and one SA serve every
    environment and every case study in this repo, with state separated by
    GCS object prefix (e.g. dev/, prod/, dev-w4/). Default 'pvc' is from
    the repo name 'pop-vibe-check'; override if the bucket name turns out
    to be globally taken in GCS (bucket names are GCP-wide unique).
  EOT
  type        = string
  default     = "pvc"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", var.name_prefix)) && length(var.name_prefix) <= 12
    error_message = "name_prefix must be 2-12 chars, lowercase alphanumeric or hyphen, start with a letter, end alphanumeric."
  }
}

variable "region" {
  description = "GCP region for regional resources. Project standard is europe-central2."
  type        = string
  default     = "europe-central2"
}

variable "billing_account_id" {
  description = <<-EOT
    Billing account ID in the form 'XXXXXX-YYYYYY-ZZZZZZ'. When set, the
    Terraform runner SA is granted roles/billing.costsManager on the
    billing account so later configurations can create budget alerts.
    Leave empty to skip; budgets must then be applied with a human
    identity until this is filled in.
  EOT
  type        = string
  default     = ""
}

variable "force_destroy_state_bucket" {
  description = <<-EOT
    Escape hatch for destroying the state bucket when it still contains
    objects (state files from envs/* compositions, including noncurrent
    versions since versioning is on). Default false keeps the safety bar
    in place — a non-empty bucket cannot be deleted, which protects
    production state. Flip to true only via -var on a one-off
    apply+destroy; do NOT leave true in committed code.
  EOT
  type        = bool
  default     = false
}
