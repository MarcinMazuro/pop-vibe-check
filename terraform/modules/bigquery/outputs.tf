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

output "reporting_dataset_id" {
  description = "Short ID of the reporting dataset holding the authorized views. This is the dataset a Looker Studio data source connects to."
  value       = google_bigquery_dataset.reporting.dataset_id
}

output "report_view_ids" {
  description = "Map of purpose → fully-qualified view reference (PROJECT.DATASET.VIEW) for the Looker Studio data sources. The views are created by Dataform (definitions/reporting/), so the names here are a contract with that project, not resource references."
  value = {
    for purpose, view in {
      events                  = "v_events"
      sentiment_daily         = "v_sentiment_daily"
      sentiment_events        = "v_sentiment_by_event"
      source_coverage         = "v_source_coverage"
      sentiment_by_period     = "v_sentiment_by_period"
      sentiment_event_sources = "v_sentiment_by_event_source"
      event_lift              = "v_event_lift"
      source_divergence       = "v_source_divergence"
    } : purpose => "${var.project_id}.${google_bigquery_dataset.reporting.dataset_id}.${view}"
  }
}

output "dataform_assertions_dataset_id" {
  description = "Short ID of the dataset holding Dataform's assertion views; null when dataform_sa_email is not set."
  value       = one(google_bigquery_dataset.dataform_assertions[*].dataset_id)
}
