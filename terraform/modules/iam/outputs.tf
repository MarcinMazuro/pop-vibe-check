output "collector_reddit_sa_email" {
  description = "Email of the Reddit collector workload SA."
  value       = google_service_account.workload["collector-reddit"].email
}

output "collector_youtube_sa_email" {
  description = "Email of the YouTube collector workload SA."
  value       = google_service_account.workload["collector-youtube"].email
}

output "publisher_sa_email" {
  description = "Email of the replay publisher workload SA."
  value       = google_service_account.workload["publisher"].email
}

output "cloud_build_sa_email" {
  description = "Email of the per-env Cloud Build runner SA."
  value       = google_service_account.workload["cloud-build"].email
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
