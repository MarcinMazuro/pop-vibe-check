# Launch parameters for the streaming pipeline. PR 3's
# `gcloud dataflow flex-template run` reads these from `terraform output`
# (re-exported at the env level) instead of hardcoding self-links, bucket
# paths, and table refs.

output "worker_sa_email" {
  description = "Worker SA the job runs as. Launch: --service-account-email."
  value       = var.dataflow_worker_sa_email
}

output "region" {
  description = "Region the job runs in. Launch: --region."
  value       = var.region
}

output "subnetwork" {
  description = "Subnet self-link the workers run in. Launch: --subnetwork."
  value       = var.subnetwork_self_link
}

output "network" {
  description = "VPC self-link. Informational; --subnetwork alone suffices for a regional launch."
  value       = var.network_self_link
}

output "worker_network_tag" {
  description = "Network tag the inter-worker firewall rule targets (Dataflow auto-applies it to worker VMs)."
  value       = var.worker_network_tag
}

output "temp_location" {
  description = "GCS temp location. Launch: --temp-location."
  value       = local.temp_location
}

output "staging_location" {
  description = "GCS staging location. Launch: --staging-location."
  value       = local.staging_location
}

output "template_spec_dir" {
  description = "GCS prefix the Flex Template spec JSON is written under (built in PR 3). Survives the dataflow-temp lifecycle rule."
  value       = local.template_spec_dir
}

output "input_subscription" {
  description = "Pub/Sub subscription the pipeline consumes. Launch: --parameters input_subscription=..."
  value       = var.dataflow_subscription_id
}

output "dlq_topic" {
  description = "Dead-letter topic the pipeline publishes unparseable records to. Launch: --parameters dlq_topic=..."
  value       = var.dlq_topic_id
}

output "events_landing_table" {
  description = "BigQuery write target (PROJECT:DATASET.TABLE). The pipeline's BigQueryIO sink writes here."
  value       = local.events_landing_table
}

output "events_table" {
  description = "BigQuery analytical table (PROJECT:DATASET.TABLE). MERGE target, not a Dataflow write target — provided so the promotion step reads it from the same place."
  value       = local.events_table
}
