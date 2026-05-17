variable "project_id" {
  description = "Target GCP project ID for the dev environment."
  type        = string
}

variable "region" {
  description = "GCP region for regional resources. Project standard is europe-central2."
  type        = string
  default     = "europe-central2"
}
