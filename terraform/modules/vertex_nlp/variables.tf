variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "name_prefix" {
  description = "Short release prefix prepended to Workbench and Endpoint names (e.g. 'co' for Clair Obscur)."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", var.name_prefix)) && length(var.name_prefix) <= 8
    error_message = "name_prefix must be 2-8 chars, lowercase alphanumeric or hyphen, start with a letter, end alphanumeric."
  }
}

variable "env" {
  description = "Environment name (e.g. 'dev', 'prod'). Suffixed into resource names."
  type        = string
}

variable "region" {
  description = "GCP region for the Vertex AI Endpoint. Project standard is europe-central2. Workbench lives in a zone of this region (see workbench_zone)."
  type        = string
}

variable "labels" {
  description = "Labels applied to every resource that supports them."
  type        = map(string)
}

variable "trainer_sa_email" {
  description = "Email of the ML trainer SA — attached to Workbench, granted roles/aiplatform.user so it can upload models and (when the endpoint is up) deploy them."
  type        = string
}

variable "dataflow_worker_sa_email" {
  description = "Email of the Dataflow worker SA — granted roles/aiplatform.user so ClassifyBatch can call Endpoint.predict. Always granted; the endpoint itself stays gated."
  type        = string
}

variable "network_id" {
  description = "Fully-qualified VPC resource ID the Workbench instance attaches to (Private Google Access, no public IP)."
  type        = string
}

variable "subnet_id" {
  description = "Fully-qualified subnet resource ID the Workbench instance attaches to."
  type        = string
}

variable "enable_workbench" {
  description = <<-EOT
    Create the T4 Workbench instance. Default false so `terraform apply`
    never starts a GPU. Flip to true for a training session, then stop
    the instance (or set enable_workbench back to false) when finished.
    Even when true, workbench_desired_state defaults to STOPPED so the
    VM exists without burning GPU hours until an operator starts it.
  EOT
  type        = bool
  default     = false
}

variable "workbench_zone" {
  description = <<-EOT
    Zone for the Workbench VM. NVIDIA T4 is available in europe-central2-b
    and europe-central2-c, not in europe-central2-a. Default -b.
  EOT
  type        = string
  default     = "europe-central2-b"

  validation {
    condition     = can(regex("^europe-central2-[bc]$", var.workbench_zone))
    error_message = "workbench_zone must be europe-central2-b or europe-central2-c (T4 is not in -a)."
  }
}

variable "workbench_machine_type" {
  description = "GCE machine type for Workbench. n1-standard-8 is the documented pairing with a single T4."
  type        = string
  default     = "n1-standard-8"
}

variable "workbench_idle_timeout_seconds" {
  description = "Idle shutdown for the Workbench VM, in seconds. 10800 = 3 hours. The instance stops itself if Jupyter is unused; GPU billing stops with it."
  type        = number
  default     = 10800
}

variable "workbench_desired_state" {
  description = "ACTIVE or STOPPED. Default STOPPED so enabling the resource still does not start the GPU until an operator opts in."
  type        = string
  default     = "STOPPED"

  validation {
    condition     = contains(["ACTIVE", "STOPPED"], var.workbench_desired_state)
    error_message = "workbench_desired_state must be ACTIVE or STOPPED."
  }
}

variable "workbench_owners" {
  description = "IAM emails granted instance owner on the Workbench VM (can open Jupyter). Empty is valid when the instance is gated off; set this before enable_workbench=true."
  type        = list(string)
  default     = []
}

variable "enable_endpoint" {
  description = <<-EOT
    Create the Vertex AI Endpoint resource. Default false so `terraform apply`
    does not expose a serving endpoint. Model versions are training artifacts
    and are *not* stored in Terraform state — this flag only creates the
    empty Endpoint. Deploying a model onto it (the GPU/CPU replica) is a
    runbook step, not an apply.
  EOT
  type        = bool
  default     = false
}
