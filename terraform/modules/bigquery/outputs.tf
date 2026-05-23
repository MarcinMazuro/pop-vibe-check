output "dataset_id" {
  description = "Short dataset ID (e.g. 'co_analytics_dev'). Use in BigQuery SQL references like `project.dataset.table`."
  value       = google_bigquery_dataset.analytics.dataset_id
}

output "dataset_full_id" {
  description = "Fully-qualified dataset resource ID. Use when an IAM binding wants the resource ID."
  value       = google_bigquery_dataset.analytics.id
}

output "dataset_location" {
  description = "Region the dataset lives in. Tables created in the dataset inherit this location."
  value       = google_bigquery_dataset.analytics.location
}
