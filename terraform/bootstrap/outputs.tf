output "state_bucket_name" {
  description = "Name of the GCS bucket that hosts Terraform remote state. Used as the 'bucket' value in terraform/envs/*/backend.tf."
  value       = google_storage_bucket.tf_state.name
}

output "state_bucket_url" {
  description = "gs:// URL of the Terraform state bucket."
  value       = google_storage_bucket.tf_state.url
}

output "runner_service_account_email" {
  description = "Email of the long-lived Terraform runner service account. Configure terraform/envs/*/providers.tf to impersonate this identity."
  value       = google_service_account.tf_runner.email
}

output "runner_service_account_id" {
  description = "Fully-qualified resource ID (projects/.../serviceAccounts/...) of the Terraform runner SA."
  value       = google_service_account.tf_runner.id
}
