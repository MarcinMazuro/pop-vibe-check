variable "project_id" {
  description = "Target GCP project ID where bootstrap resources are created."
  type        = string
}

variable "env" {
  description = "Environment name used in resource names and labels. Bootstrap is normally applied for 'dev' first."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "prod"], var.env)
    error_message = "env must be one of: dev, prod."
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
