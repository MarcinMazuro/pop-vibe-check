variable "project_id" {
  description = "Target GCP project ID. prod shares the project with dev: the environments are separated by resource name suffix and Terraform state prefix, not by project."
  type        = string
}

variable "region" {
  description = "GCP region for regional resources. Project standard is europe-central2."
  type        = string
  default     = "europe-central2"
}

variable "name_prefix" {
  description = <<-EOT
    Short prefix for every release-specific resource name (e.g. 'co' for
    Clair Obscur). Keep it the same as dev: the suffix is what separates
    the environments, so co-raw-archive-prod sits beside
    co-raw-archive-dev.
  EOT
  type        = string
  default     = "co"
}

variable "billing_account_id" {
  description = "Billing account the budget hangs off. Must be the account the project is linked to, or the budget sees $0 spend."
  type        = string
}

variable "monthly_budget_amount" {
  description = "Monthly budget cap for prod in the billing account's currency. prod is idle except during a demonstration, so this is a tripwire rather than a forecast."
  type        = number
}

variable "notification_emails" {
  description = "Emails that receive budget and alert notifications. Each must click GCP's verification link before delivery starts."
  type        = list(string)
  default     = []
}

variable "report_viewer_emails" {
  description = "User emails allowed to read the reporting views (the dashboard's readers). They get no access to the analytics dataset."
  type        = list(string)
  default     = []
}

variable "dataflow_max_job_runtime_hours" {
  description = "Hours a Dataflow job may run before the cost alert fires. Tighter than dev by default: a prod replay is a demonstration, not an experiment."
  type        = number
  default     = 3
}

variable "replay_backlog_age_alert_seconds" {
  description = "How old the oldest unacknowledged message on the Dataflow subscription may get before alerting."
  type        = number
  default     = 1800
}

variable "youtube_image_uri" {
  description = "Image the YouTube collector job is created with. There are no prod image triggers yet, so this stays on the public 'pause' placeholder until pointed at a digest."
  type        = string
  default     = "gcr.io/google-containers/pause"
}

variable "steam_image_uri" {
  description = "Image the Steam collector job is created with. See youtube_image_uri."
  type        = string
  default     = "gcr.io/google-containers/pause"
}

variable "publisher_image_uri" {
  description = "Image the publisher job is created with. See youtube_image_uri."
  type        = string
  default     = "gcr.io/google-containers/pause"
}
