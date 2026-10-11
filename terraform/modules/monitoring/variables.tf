variable "project_id" {
  description = "GCP project ID the alert policies live in."
  type        = string
}

variable "name_prefix" {
  description = "Short release prefix, used in alert display names."
  type        = string
}

variable "env" {
  description = "Environment name, used in alert display names."
  type        = string
}

variable "region" {
  description = "Region the Dataflow jobs run in. Only used in the alert documentation (drain command)."
  type        = string
}

variable "notification_channel_ids" {
  description = "Monitoring notification channel IDs every policy notifies. Pass the budgets module's notification_channel_ids so alerts reach the same recipients as budget alerts."
  type        = list(string)
}

variable "dataflow_subscription_name" {
  description = "Short name of the Pub/Sub subscription the pipeline consumes, for the backlog policy."
  type        = string
}

variable "dlq_subscription_name" {
  description = "Short name of the dead-letter inspection subscription, for the dead-letter policy."
  type        = string
}

variable "max_job_runtime_hours" {
  description = "Hours a Dataflow job may run before the cost alert fires. Replays in this project are minutes to hours; the default leaves room for a full realtime-preset run."
  type        = number
  default     = 6
}

variable "backlog_age_alert_seconds" {
  description = "How old the oldest unacknowledged message on the Dataflow subscription may get before alerting. Must exceed the pacing of a normal replay."
  type        = number
  default     = 1800
}
