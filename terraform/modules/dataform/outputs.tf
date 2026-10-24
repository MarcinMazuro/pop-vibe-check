output "repository_name" {
  description = "Short name of the Dataform repository (e.g. 'co-reporting-dev'). The deploy build calls the API on it."
  value       = google_dataform_repository.this.name
}

output "repository_id" {
  description = "Fully-qualified repository resource ID (projects/.../locations/.../repositories/...)."
  value       = google_dataform_repository.this.id
}

output "github_token_secret_id" {
  description = "Secret ID holding the GitHub token the repository fetches with. Populate with `gcloud secrets versions add`."
  value       = google_secret_manager_secret.github_token.secret_id
}

output "service_agent_email" {
  description = "Email of the project's Dataform service agent — the identity that reads the token and mints dataform_sa_email tokens."
  value       = local.service_agent_email
}
