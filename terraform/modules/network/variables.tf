variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "name_prefix" {
  description = "Short release prefix prepended to network and subnet names."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", var.name_prefix)) && length(var.name_prefix) <= 8
    error_message = "name_prefix must be 2-8 chars, lowercase alphanumeric or hyphen, start with a letter, end alphanumeric."
  }
}

variable "env" {
  description = "Environment name (e.g. 'dev', 'prod'). Suffixed into network and subnet names."
  type        = string
}

variable "region" {
  description = "GCP region for the subnet. Project standard is europe-central2."
  type        = string
}

variable "subnet_cidr" {
  description = "Primary CIDR for the subnet. /24 is plenty for the planned workloads (Dataflow up to 5 workers, occasional Cloud Run with Direct VPC)."
  type        = string
  default     = "10.10.0.0/24"

  validation {
    condition     = can(cidrhost(var.subnet_cidr, 0))
    error_message = "subnet_cidr must be a valid CIDR block (e.g. '10.10.0.0/24')."
  }
}
