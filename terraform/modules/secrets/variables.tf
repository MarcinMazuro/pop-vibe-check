variable "project_id" {
  description = "GCP project ID — used in fully-qualified secret resource IDs surfaced as outputs."
  type        = string
}

variable "name_prefix" {
  description = "Short release prefix prepended to every secret name (e.g. 'co' for Clair Obscur, 'w4' for Witcher 4)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", var.name_prefix)) && length(var.name_prefix) <= 8
    error_message = "name_prefix must be 2-8 chars, lowercase alphanumeric or hyphen, start with a letter, end alphanumeric."
  }
}

variable "env" {
  description = "Environment name (e.g. 'dev', 'prod'). Suffixed into secret IDs."
  type        = string
}

variable "labels" {
  description = "Labels applied to every secret container."
  type        = map(string)
}

variable "collector_reddit_sa_email" {
  description = "Email of the Reddit collector SA — granted secretAccessor on every reddit-* secret and on the author-hash-salt."
  type        = string
}

variable "collector_youtube_sa_email" {
  description = "Email of the YouTube collector SA — granted secretAccessor on the youtube-api-key secret and on the author-hash-salt."
  type        = string
}
