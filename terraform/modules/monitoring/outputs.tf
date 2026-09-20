output "alert_policy_names" {
  description = "Resource names of every alert policy this module manages."
  value = [
    google_monitoring_alert_policy.dataflow_job_failed.name,
    google_monitoring_alert_policy.dataflow_job_running_too_long.name,
    google_monitoring_alert_policy.pubsub_backlog_ageing.name,
    google_monitoring_alert_policy.dlq_not_empty.name,
  ]
}
