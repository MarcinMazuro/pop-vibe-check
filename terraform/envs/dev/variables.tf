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
