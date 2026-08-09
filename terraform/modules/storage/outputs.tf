output "raw_archive_bucket_name" {
  description = "Name of the raw archive bucket. Wire into collector jobs as TARGET_BUCKET."
  value       = google_storage_bucket.raw_archive.name
}

output "raw_archive_bucket_url" {
  description = "gs:// URL of the raw archive bucket."
  value       = google_storage_bucket.raw_archive.url
}

output "tf_artifacts_bucket_name" {
  description = "Name of the Cloud Build / Terraform artifacts bucket."
  value       = google_storage_bucket.tf_artifacts.name
}

output "tf_artifacts_bucket_url" {
  description = "gs:// URL of the artifacts bucket."
  value       = google_storage_bucket.tf_artifacts.url
}

output "dataflow_temp_bucket_name" {
  description = "Name of the Dataflow staging/temp bucket."
  value       = google_storage_bucket.dataflow_temp.name
}

output "dataflow_temp_bucket_url" {
  description = "gs:// URL of the Dataflow staging/temp bucket. Dataflow launch params derive from it: staging at {url}/staging, temp at {url}/temp, Flex Template spec under {url}/templates."
  value       = google_storage_bucket.dataflow_temp.url
}
