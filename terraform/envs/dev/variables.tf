variable "project_id" {
  description = "Target GCP project ID for the dev environment."
  type        = string
}

variable "region" {
  description = "GCP region for regional resources. Project standard is europe-central2."
  type        = string
  default     = "europe-central2"
}

variable "name_prefix" {
  description = <<-EOT
    Short prefix for every release-specific resource name created in this
    composition (e.g. 'co' for Clair Obscur, 'w4' for Witcher 4). Multiple
    case studies can coexist in one GCP project by sharing this directory
    with different state files. Bootstrap resources (state bucket, runner
    SA) keep their original 'co-' prefix and are not affected.
  EOT
  type        = string
  default     = "co"
}

variable "billing_account_id" {
  description = "Billing account ID ('XXXXXX-YYYYYY-ZZZZZZ') the budget module hangs off. Must be the account the project is linked to (`gcloud billing projects describe`); a mismatch makes the budget see $0 spend. Same value is passed to terraform/bootstrap so the runner SA can manage budgets on that account."
  type        = string
}

variable "monthly_budget_amount" {
  description = "Monthly budget cap for this env in the billing account's default currency (PLN for Poland-billed accounts). Set this to your personal monthly spend limit — alerts fire at percentages of this number."
  type        = number
}

variable "notification_emails" {
  description = "Emails that receive budget alerts. Each becomes a Cloud Monitoring email channel; recipient must click a verification link from GCP before delivery actually starts."
  type        = list(string)
  default     = []
}

variable "enable_nlp_workbench" {
  description = <<-EOT
    Create the Vertex AI Workbench instance used to fine-tune DistilBERT.
    Default false: a routine apply must not start a training VM.
    CPU-only (leave nlp_workbench_accelerator_count at 0). See
    terraform/modules/vertex_nlp/README.md for the start/stop runbook.
  EOT
  type        = bool
  default     = false
}

variable "nlp_workbench_desired_state" {
  description = "ACTIVE or STOPPED for the Workbench VM. Ignored while enable_nlp_workbench is false. Default STOPPED."
  type        = string
  default     = "STOPPED"
}

variable "nlp_workbench_owners" {
  description = "Emails granted Workbench instance owner (Jupyter access). Set these before flipping enable_nlp_workbench."
  type        = list(string)
  default     = []
}

variable "nlp_workbench_machine_type" {
  description = "GCE machine type for Workbench. Default e2-standard-4 (CPU). Use e2-standard-8 if training OOMs."
  type        = string
  default     = "e2-standard-4"
}

variable "nlp_workbench_accelerator_type" {
  description = "Guest accelerator type. Leave empty (CPU-only)."
  type        = string
  default     = ""
}

variable "nlp_workbench_accelerator_count" {
  description = "Guest accelerator count. Keep at 0 (CPU-only)."
  type        = number
  default     = 0
}

variable "nlp_workbench_idle_timeout_seconds" {
  description = "Workbench idle shutdown in seconds. 0 disables auto-stop (default). Enabled range 600–86400; 10800 is 3 hours."
  type        = number
  default     = 0
}

variable "enable_nlp_endpoint" {
  description = <<-EOT
    Create the (empty) Vertex AI Endpoint. Default false. Deploying a
    model replica onto it is a runbook step, not this flag — see
    nlp/endpoint/register.py.
  EOT
  type        = bool
  default     = false
}

variable "github_app_installation_id" {
  description = "Installation ID of the Google Cloud Build GitHub App on the repository owner (the number at the end of github.com/settings/installations/<id>). null keeps the Cloud Build connection and triggers uncreated. See modules/cloud_build/README.md."
  type        = number
  default     = null
}

variable "cloud_build_approver_emails" {
  description = "User emails allowed to approve the queued terraform apply build on main."
  type        = list(string)
  default     = []
}

variable "dataflow_max_job_runtime_hours" {
  description = "Hours a Dataflow job may run before the cost alert fires. Streaming jobs bill until drained; every replay here is minutes to hours."
  type        = number
  default     = 6
}

variable "replay_backlog_age_alert_seconds" {
  description = "How old the oldest unacknowledged message on the Dataflow subscription may get before alerting. Must exceed the pacing of a normal replay."
  type        = number
  default     = 1800
}

variable "report_viewer_emails" {
  description = "User emails allowed to read the reporting dataset's authorized views (the Looker Studio dashboard's readers). They get no access to the analytics dataset."
  type        = list(string)
  default     = []
}
