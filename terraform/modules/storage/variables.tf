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
