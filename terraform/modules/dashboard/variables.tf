variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "name_prefix" {
  description = "Short release prefix prepended to the service name."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]*[a-z0-9]$", var.name_prefix)) && length(var.name_prefix) <= 8
    error_message = "name_prefix must be 2-8 chars, lowercase alphanumeric or hyphen, start with a letter, end alphanumeric."
  }
}

variable "env" {
  description = "Environment name (e.g. 'dev', 'prod'). Suffixed into the service name."
  type        = string
}

variable "region" {
  description = "Region the service runs in."
  type        = string
}

variable "labels" {
  description = "Labels applied to the service."
  type        = map(string)
}

variable "dashboard_sa_email" {
  description = "Runtime identity of the service. Granted dataViewer on the reporting dataset and jobUser on the project."
  type        = string
}

variable "reporting_dataset_id" {
  description = "Short id of the dataset holding the authorized views (e.g. 'co_reporting_dev'). Wired into REPORTING_DATASET."
  type        = string
}

variable "viewer_emails" {
  description = "User emails allowed through IAP to open the dashboard. Granted roles/iap.httpsResourceAccessor on the project."
  type        = list(string)
  default     = []
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

variable "max_instances" {
  description = "Upper bound on instances. A handful of viewers fit on one; the cap is a cost guard, since every instance queries BigQuery on its own cache."
  type        = number
  default     = 2
}

variable "request_timeout" {
  description = "Longest a request may stay open. Bounds a Streamlit websocket session before the browser reconnects; 3600s is the Cloud Run maximum."
  type        = string
  default     = "3600s"
}

variable "deployer_sa_email" {
  description = "Service account that deploys new images to the service (the per-env Cloud Build SA). Granted run.developer on the service and actAs on its runtime SA. null skips the grants."
  type        = string
  default     = null
}
