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

variable "enabled_services" {
  description = <<-EOT
    Set of GCP APIs that bootstrap keeps enabled on the project. Default
    covers every service needed by Phase 0 + Phase 1 modules. Listed here
    so 'gcloud services enable' is no longer a manual prerequisite once
    bootstrap has been applied — Terraform re-enables anything GCP turns
    off (e.g. after periods of inactivity).

    Note: the *first ever* apply of bootstrap on a brand-new project still
    requires the trio (cloudresourcemanager, iam, serviceusage) enabled by
    hand via gcloud; bootstrap cannot enable them via Terraform if it
    cannot reach the APIs needed to enable them. After the first apply
    this list takes over.
  EOT
  type        = set(string)
  default = [
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "billingbudgets.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "compute.googleapis.com",
    "dataflow.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "serviceusage.googleapis.com",
    "storage.googleapis.com",
  ]
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
