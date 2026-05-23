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
  description = "Billing account ID ('XXXXXX-YYYYYY-ZZZZZZ') the budget module hangs off. Same value passed to terraform/bootstrap; duplicated here so envs/dev is self-contained."
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
