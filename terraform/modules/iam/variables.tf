variable "project_id" {
  description = "GCP project ID. Used to compose SA emails in outputs."
  type        = string
}

variable "name_prefix" {
  description = "Short release prefix prepended to every SA account_id (e.g. 'co' for Clair Obscur, 'w4' for Witcher 4)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", var.name_prefix)) && length(var.name_prefix) <= 8
    error_message = "name_prefix must be 2-8 chars, lowercase alphanumeric or hyphen, start with a letter, end alphanumeric."
  }
}

variable "env" {
  description = "Environment name (e.g. 'dev', 'prod'). Suffixed into account_ids so dev and prod each own their workload identities."
  type        = string
}
