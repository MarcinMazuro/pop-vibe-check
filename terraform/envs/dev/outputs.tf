output "raw_archive_bucket_name" {
  description = "Name of the raw archive bucket. Collectors set TARGET_BUCKET to this value."
  value       = module.storage.raw_archive_bucket_name
}

output "tf_artifacts_bucket_name" {
  description = "Name of the Cloud Build / Terraform artifacts bucket."
  value       = module.storage.tf_artifacts_bucket_name
}

output "collector_reddit_sa_email" {
  description = "Email of the Reddit collector workload SA."
  value       = module.iam.collector_reddit_sa_email
}

output "collector_youtube_sa_email" {
  description = "Email of the YouTube collector workload SA."
  value       = module.iam.collector_youtube_sa_email
}

output "cloud_build_sa_email" {
  description = "Email of the Cloud Build runner SA for this env."
  value       = module.iam.cloud_build_sa_email
}

output "secret_names" {
  description = "Map of short purpose name → actual secret_id. Use these in 'gcloud secrets versions add' to populate values."
  value       = module.secrets.secret_names
}

output "image_repository_url" {
  description = "Image-URI prefix for the Artifact Registry repository. Append '/IMAGE:TAG' to address a specific image (e.g. for Cloud Run Job image config)."
  value       = module.artifact_registry.repository_url
}

output "network_self_link" {
  description = "Self-link URL of the dev VPC. Used by Dataflow's network field and Cloud Run Direct VPC egress."
  value       = module.network.network_self_link
}

output "subnet_self_link" {
  description = "Self-link URL of the dev subnet."
  value       = module.network.subnet_self_link
}

output "analytics_dataset_id" {
  description = "Short BigQuery dataset ID (e.g. 'co_analytics_dev') for the analytical events table and authorized views."
  value       = module.bigquery.dataset_id
}
