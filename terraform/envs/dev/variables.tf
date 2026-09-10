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
    Default false: a routine apply must not start a training VM. CPU-only
    unless nlp_workbench_accelerator_count is set. See
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
  description = "Guest accelerator type. Empty with count 0 (CPU-only). NVIDIA_TESLA_T4 only when count is 1."
  type        = string
  default     = ""
}

variable "nlp_workbench_accelerator_count" {
  description = "Guest accelerator count. Default 0 (no NVIDIA). Do not set to 1 on free-tier billing."
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
