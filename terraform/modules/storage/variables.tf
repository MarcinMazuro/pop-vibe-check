variable "name_prefix" {
  description = "Short prefix prepended to every bucket name (e.g. 'co' for Clair Obscur, 'w4' for Witcher 4). Lets multiple case studies coexist in one GCP project."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", var.name_prefix)) && length(var.name_prefix) <= 8
    error_message = "name_prefix must be 2-8 chars, lowercase alphanumeric or hyphen, start with a letter, end alphanumeric."
  }
}

variable "env" {
  description = "Environment name (e.g. 'dev', 'prod'). Suffixed into bucket names."
  type        = string
}

variable "region" {
  description = "GCP region for the buckets. Project standard is europe-central2."
  type        = string
}

variable "labels" {
  description = "Labels applied to every bucket created by this module."
  type        = map(string)
}

variable "dataflow_worker_sa_email" {
  description = "Email of the Dataflow worker SA — granted roles/storage.objectAdmin on the dataflow-temp bucket so workers can write staging and temp objects."
  type        = string
}

variable "ml_trainer_sa_email" {
  description = "Email of the ML trainer SA — granted roles/storage.objectAdmin on the artifacts bucket so Workbench can cache Hugging Face datasets and write MLflow runs under the nlp/ prefix."
  type        = string
}

variable "raw_archive_autodelete_days" {
  description = <<-EOT
    If greater than 0, raw archive objects are hard-deleted after this many
    days. 0 (default) disables auto-delete and the raw archive grows
    indefinitely. The Standard → Coldline transition at 30 days is always
    enabled regardless of this value.
  EOT
  type        = number
  default     = 0

  validation {
    condition     = var.raw_archive_autodelete_days >= 0
    error_message = "raw_archive_autodelete_days must be >= 0."
  }
}

variable "force_destroy_raw_archive" {
  description = <<-EOT
    Escape hatch for destroying the raw archive bucket when it still
    contains objects. Default false keeps the safety bar in place — the
    archive is the only re-runnable source of truth for collector data,
    accidental deletion is unrecoverable. Flip to true via -var on a
    one-off teardown; do NOT leave true in committed code.
  EOT
  type        = bool
  default     = false
}

variable "force_destroy_artifacts" {
  description = <<-EOT
    Escape hatch for destroying the Cloud Build / Terraform artifacts
    bucket when it still contains objects. Default false — the contents
    are disposable build logs, so the bar is less critical than for raw
    archive, but still gated to avoid surprise destroys. Flip to true via
    -var on a one-off teardown.
  EOT
  type        = bool
  default     = false
}

variable "force_destroy_dataflow_temp" {
  description = <<-EOT
    Escape hatch for destroying the Dataflow staging/temp bucket when it
    still contains objects. Default false. The staging/ and temp/ prefixes
    are disposable, but templates/ holds the Flex Template spec a running
    or future job launches from — do not force-destroy while a template is
    in use. Flip to true via -var on a one-off teardown.
  EOT
  type        = bool
  default     = false
}
