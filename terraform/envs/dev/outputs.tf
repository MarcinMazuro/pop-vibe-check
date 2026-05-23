output "raw_archive_bucket_name" {
  description = "Name of the raw archive bucket. Collectors set TARGET_BUCKET to this value."
  value       = module.storage.raw_archive_bucket_name
}

output "tf_artifacts_bucket_name" {
  description = "Name of the Cloud Build / Terraform artifacts bucket."
  value       = module.storage.tf_artifacts_bucket_name
}
