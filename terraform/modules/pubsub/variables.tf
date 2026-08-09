variable "project_id" {
  description = "GCP project ID."
  type        = string
}

variable "name_prefix" {
  description = "Short release prefix prepended to topic and subscription names."
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

variable "labels" {
  description = "Labels applied to the topic and subscription."
  type        = map(string)
}

variable "publisher_sa_email" {
  description = "Email of the replay publisher SA — granted roles/pubsub.publisher on the events topic."
  type        = string
}

variable "dataflow_worker_sa_email" {
  description = "Email of the Dataflow worker SA — granted roles/pubsub.subscriber on the Dataflow subscription and roles/pubsub.publisher on the DLQ topic (for the pipeline's explicit dead-letter output)."
  type        = string
}
