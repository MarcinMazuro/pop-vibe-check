output "collector_reddit_sa_email" {
  description = "Email of the Reddit collector workload SA."
  value       = google_service_account.workload["collector-reddit"].email
}

output "collector_youtube_sa_email" {
  description = "Email of the YouTube collector workload SA."
  value       = google_service_account.workload["collector-youtube"].email
}

output "collector_steam_sa_email" {
  description = "Email of the Steam collector workload SA."
  value       = google_service_account.workload["collector-steam"].email
}

output "publisher_sa_email" {
  description = "Email of the replay publisher workload SA."
  value       = google_service_account.workload["publisher"].email
}

output "cloud_build_sa_email" {
  description = "Email of the per-env Cloud Build runner SA."
  value       = google_service_account.workload["cloud-build"].email
}

output "dataflow_worker_sa_email" {
  description = "Email of the Dataflow worker SA — the streaming pipeline's runtime identity."
  value       = google_service_account.workload["dataflow-worker"].email
}

output "ml_trainer_sa_email" {
  description = "Email of the ML trainer SA — attached to Vertex AI Workbench and used to upload models to Vertex AI Model Registry."
  value       = google_service_account.workload["ml-trainer"].email
}

output "dashboard_sa_email" {
  description = "Email of the dashboard SA — the Streamlit Cloud Run service's runtime identity."
  value       = google_service_account.workload["dashboard"].email
}

output "dataform_sa_email" {
  description = "Email of the Dataform SA — the identity the Dataform repository's workflow invocations run as."
  value       = google_service_account.workload["dataform"].email
}

output "service_accounts" {
  description = "Map of workload short name → SA email. Convenient for iterating in downstream modules (e.g. for_each over collector SAs when granting bucket access)."
  value = {
    for k, sa in google_service_account.workload : k => sa.email
  }
}

output "service_account_ids" {
  description = "Map of workload short name → fully-qualified SA resource ID (projects/.../serviceAccounts/...). Use when an IAM binding wants the resource ID instead of the email."
  value = {
    for k, sa in google_service_account.workload : k => sa.id
  }
}
