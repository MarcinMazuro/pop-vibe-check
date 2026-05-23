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
