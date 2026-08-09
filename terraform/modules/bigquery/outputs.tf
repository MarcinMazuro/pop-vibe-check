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

output "raw_landing_table_id" {
  description = "Short table id of the truncate-and-load landing table (e.g. 'raw_landing')."
  value       = google_bigquery_table.raw_landing.table_id
}

output "raw_staging_table_id" {
  description = "Short table id of the deduplicated staging table the publisher replays from (e.g. 'raw_staging')."
  value       = google_bigquery_table.raw_staging.table_id
}

output "events_landing_table_id" {
  description = "Short table id of the append-only Dataflow write target (e.g. 'events_landing')."
  value       = google_bigquery_table.events_landing.table_id
}

output "events_table_id" {
  description = "Short table id of the deduplicated analytical events table (e.g. 'events'). MERGE target and Looker Studio source."
  value       = google_bigquery_table.events.table_id
}
