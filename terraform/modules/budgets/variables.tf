variable "project_id" {
  description = "GCP project ID — used in the budget's project filter and as the project for the notification channels."
  type        = string
}

variable "name_prefix" {
  description = "Short release prefix used in the budget display name and notification channel labels."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", var.name_prefix)) && length(var.name_prefix) <= 8
    error_message = "name_prefix must be 2-8 chars, lowercase alphanumeric or hyphen, start with a letter, end alphanumeric."
  }
}

variable "env" {
  description = "Environment name (e.g. 'dev', 'prod') — used in display names so dev and prod alerts are visually distinct in inboxes."
  type        = string
}

variable "billing_account_id" {
  description = "Billing account ID in the form 'XXXXXX-YYYYYY-ZZZZZZ' that the budget hangs off."
  type        = string

  validation {
    condition     = can(regex("^[0-9A-F]{6}-[0-9A-F]{6}-[0-9A-F]{6}$", var.billing_account_id))
    error_message = "billing_account_id must look like 'XXXXXX-YYYYYY-ZZZZZZ' (six-char groups, uppercase hex)."
  }
}

variable "monthly_amount" {
  description = "Monthly budget cap, in the billing account's default currency (PLN for accounts billed in Poland). Match this to your personal monthly spend limit — alerts fire at percentages of this number."
  type        = number

  validation {
    condition     = var.monthly_amount > 0
    error_message = "monthly_amount must be positive."
  }
}

variable "threshold_percentages" {
  description = "Spend-percentage thresholds (as decimals — 0.5 = 50%) at which alerts fire."
  type        = list(number)
  default     = [0.5, 0.9, 1.0, 1.2]

  validation {
    condition     = alltrue([for t in var.threshold_percentages : t > 0])
    error_message = "thresholds must all be positive."
  }
}

variable "notification_emails" {
  description = "Email addresses that receive budget alerts. Each becomes a Cloud Monitoring email notification channel; the recipient must click a verification link from GCP before the channel actually delivers."
  type        = list(string)
  default     = []
}

variable "include_credits" {
  description = "Whether GCP credits (free-tier, promotional) count against the budget. Default true — alerts reflect what GCP would charge if credits ran out, which is the conservative read."
  type        = bool
  default     = true
}
