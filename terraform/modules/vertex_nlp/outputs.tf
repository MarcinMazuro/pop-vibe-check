output "trainer_sa_email" {
  description = "Email of the ML trainer SA this module was wired with."
  value       = var.trainer_sa_email
}

output "workbench_enabled" {
  description = "Whether the T4 Workbench instance currently exists (enable_workbench)."
  value       = var.enable_workbench
}

output "workbench_name" {
  description = "Short Workbench instance name, or empty when gated off."
  value       = var.enable_workbench ? local.workbench_name : ""
}

output "workbench_id" {
  description = "Fully-qualified Workbench instance ID, or empty when gated off."
  value       = var.enable_workbench ? google_workbench_instance.nlp[0].id : ""
}

output "workbench_zone" {
  description = "Zone the Workbench instance is (or would be) created in."
  value       = var.workbench_zone
}

output "endpoint_enabled" {
  description = "Whether the Vertex AI Endpoint currently exists (enable_endpoint)."
  value       = var.enable_endpoint
}

output "endpoint_id" {
  description = "Short Endpoint id (the VERTEX_ENDPOINT_ID launch parameter), or empty when gated off."
  value       = var.enable_endpoint ? local.endpoint_id : ""
}

output "endpoint_resource_name" {
  description = "Fully-qualified Endpoint resource name (projects/.../locations/.../endpoints/...), or empty when gated off. Prefer this as VERTEX_ENDPOINT_ID — the client accepts either form."
  value       = var.enable_endpoint ? google_vertex_ai_endpoint.nlp[0].id : ""
}

output "location" {
  description = "Vertex AI location (region) for the Endpoint and Model Registry."
  value       = var.region
}
