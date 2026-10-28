variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "name_prefix" {
  description = "Short release prefix prepended to every resource name."
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
  description = "Region of the service and the Cloud SQL instance."
  type        = string
}

variable "labels" {
  description = "Labels applied to the service, the instance and the secret."
  type        = map(string)
}

variable "mlflow_sa_email" {
  description = "Runtime identity of the service. Granted cloudsql.client on the project and secretAccessor on the database password."
  type        = string
}

variable "artifact_root" {
  description = "Default artifact root for experiments the server creates, e.g. 'gs://co-tf-artifacts-dev/nlp/mlruns'. Clients write there directly; the server only reads."
  type        = string
}

variable "client_sa_emails" {
  description = "Service accounts that call the server programmatically through IAP (the Workbench trainer). Granted roles/iap.httpsResourceAccessor on the project."
  type        = list(string)
  default     = []
}

variable "tier" {
  description = "Cloud SQL machine tier. db-f1-micro is the smallest shared-core tier; the server's load is a few writes per training step."
  type        = string
  default     = "db-f1-micro"
}

variable "database_version" {
  description = "Cloud SQL Postgres version."
  type        = string
  default     = "POSTGRES_16"
}

variable "image_uri" {
  description = "Image the service is created with; ignored afterwards (Cloud Build deploys it). Default is Google's public 'hello' sample, which answers on $PORT."
  type        = string
  default     = "us-docker.pkg.dev/cloudrun/container/hello"
}

variable "memory" {
  description = "Container memory limit (Cloud Run units, e.g. '1Gi')."
  type        = string
  default     = "1Gi"
}

variable "cpu" {
  description = "Container CPU limit (Cloud Run units, e.g. '1')."
  type        = string
  default     = "1"
}

variable "deployer_sa_email" {
  description = "Service account that deploys new images to the service (the per-env Cloud Build SA). Granted run.developer on the service and actAs on its runtime SA. null skips the grants."
  type        = string
  default     = null
}
