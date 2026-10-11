output "github_token_secret_id" {
  description = "Secret ID holding the GitHub token for the connection. Populate with `gcloud secrets versions add`."
  value       = google_secret_manager_secret.github_token.secret_id
}

output "tfvars_secret_id" {
  description = "Secret ID holding the environment's canonical terraform.tfvars, read by the plan/apply builds."
  value       = google_secret_manager_secret.tfvars.secret_id
}

output "connection_name" {
  description = "Name of the GitHub connection; empty until github_app_installation_id is set."
  value       = local.github_enabled ? google_cloudbuildv2_connection.github[0].name : ""
}

output "trigger_names" {
  description = "Names of every trigger this module manages; empty until github_app_installation_id is set."
  value = concat(
    [for t in google_cloudbuild_trigger.python_checks_pr : t.name],
    [for t in google_cloudbuild_trigger.image_pr : t.name],
    [for t in google_cloudbuild_trigger.image_deploy : t.name],
    [for t in google_cloudbuild_trigger.terraform_plan_pr : t.name],
    [for t in google_cloudbuild_trigger.terraform_apply : t.name],
  )
}
