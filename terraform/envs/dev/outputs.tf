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

output "publisher_sa_email" {
  description = "Email of the replay publisher workload SA."
  value       = module.iam.publisher_sa_email
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

output "reddit_collector_job_name" {
  description = "Short name of the Reddit collector Cloud Run Job. Use in 'gcloud run jobs execute'."
  value       = module.cloud_run_jobs.reddit_job_name
}

output "youtube_collector_job_name" {
  description = "Short name of the YouTube collector Cloud Run Job."
  value       = module.cloud_run_jobs.youtube_job_name
}

output "publisher_job_name" {
  description = "Short name of the replay publisher Cloud Run Job."
  value       = module.cloud_run_jobs.publisher_job_name
}

output "events_topic_name" {
  description = "Short name of the Pub/Sub events topic the publisher replays into."
  value       = module.pubsub.events_topic_name
}

output "events_verify_subscription_name" {
  description = "Short name of the manual verification subscription. Use in 'gcloud pubsub subscriptions pull'."
  value       = module.pubsub.verify_subscription_name
}

output "events_dataflow_subscription_name" {
  description = "Short name of the Dataflow subscription the streaming pipeline consumes."
  value       = module.pubsub.dataflow_subscription_name
}

output "events_dlq_topic_name" {
  description = "Short name of the dead-letter topic."
  value       = module.pubsub.dlq_topic_name
}

output "events_dlq_subscription_name" {
  description = "Short name of the DLQ inspection subscription. Use in 'gcloud pubsub subscriptions pull' to read dead records."
  value       = module.pubsub.dlq_subscription_name
}

output "raw_staging_table_id" {
  description = "Short table id of the deduplicated staging table the publisher replays from (raw_staging). Used by the promotion coverage check to compare staged ids against landed ones."
  value       = module.bigquery.raw_staging_table_id
}

output "events_landing_table_id" {
  description = "Short table id of the append-only Dataflow write target (events_landing)."
  value       = module.bigquery.events_landing_table_id
}

output "events_table_id" {
  description = "Short table id of the analytical events table (MERGE target, Looker source)."
  value       = module.bigquery.events_table_id
}

output "dataflow_temp_bucket_name" {
  description = "Name of the Dataflow staging/temp bucket."
  value       = module.storage.dataflow_temp_bucket_name
}

# --- Dataflow launch parameters ---------------------------------------------
# PR 3's `gcloud dataflow flex-template run` reads these instead of
# hardcoding self-links, bucket paths, and table refs. See
# modules/dataflow/README.md for the full invocation.

output "dataflow_worker_sa_email" {
  description = "Worker SA the Dataflow job runs as. Launch: --service-account-email."
  value       = module.dataflow.worker_sa_email
}

output "dataflow_region" {
  description = "Region the Dataflow job runs in. Launch: --region."
  value       = module.dataflow.region
}

output "dataflow_subnetwork" {
  description = "Subnet self-link the Dataflow workers run in. Launch: --subnetwork."
  value       = module.dataflow.subnetwork
}

output "dataflow_worker_network_tag" {
  description = "Network tag the inter-worker firewall rule targets (Dataflow auto-applies it to workers)."
  value       = module.dataflow.worker_network_tag
}

output "dataflow_temp_location" {
  description = "GCS temp location. Launch: --temp-location."
  value       = module.dataflow.temp_location
}

output "dataflow_staging_location" {
  description = "GCS staging location. Launch: --staging-location."
  value       = module.dataflow.staging_location
}

output "dataflow_template_spec_dir" {
  description = "GCS prefix the Flex Template spec JSON is uploaded under (built in PR 3)."
  value       = module.dataflow.template_spec_dir
}

output "dataflow_input_subscription" {
  description = "Pub/Sub subscription the pipeline consumes. Launch: --parameters input_subscription=..."
  value       = module.dataflow.input_subscription
}

output "dataflow_dlq_topic" {
  description = "Dead-letter topic the pipeline publishes unparseable records to. Launch: --parameters dlq_topic=..."
  value       = module.dataflow.dlq_topic
}

output "dataflow_events_landing_table" {
  description = "BigQuery write target (PROJECT:DATASET.TABLE). Launch: --parameters output_table=..."
  value       = module.dataflow.events_landing_table
}

output "dataflow_events_table" {
  description = "BigQuery analytical table (PROJECT:DATASET.TABLE). Promotion MERGE target, not a Dataflow write target."
  value       = module.dataflow.events_table
}
