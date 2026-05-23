output "secret_ids" {
  description = "Map of short name → fully-qualified secret resource ID (projects/.../secrets/...). Use when wiring secrets into Cloud Run Jobs or Dataflow workers."
  value = {
    for name, secret in google_secret_manager_secret.container :
    name => secret.id
  }
}

output "secret_names" {
  description = "Map of short name → actual secret_id with prefix and env (e.g. 'reddit-client-id' → 'co-reddit-client-id-dev'). Use in 'gcloud secrets versions add' commands."
  value = {
    for name, secret in google_secret_manager_secret.container :
    name => secret.secret_id
  }
}
