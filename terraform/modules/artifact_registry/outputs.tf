output "repository_id" {
  description = "Short ID of the repository (e.g. 'co-images-dev'). Use in image references where 'location-docker.pkg.dev/project/repo/image:tag' is constructed."
  value       = google_artifact_registry_repository.images.repository_id
}

output "repository_full_id" {
  description = "Fully-qualified repository resource ID (projects/.../locations/.../repositories/...). Useful for IAM bindings in downstream modules."
  value       = google_artifact_registry_repository.images.id
}

output "repository_url" {
  description = "Image-URI prefix for this repository: 'LOCATION-docker.pkg.dev/PROJECT/REPO'. Append '/IMAGE:TAG' to address a specific image."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.images.repository_id}"
}
