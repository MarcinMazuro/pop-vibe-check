# ----------------------------------------------------------------------------
# Docker repository for collector, publisher, and Dataflow Flex Template
# container images.
#
# One repository per release × env so dev and prod cannot reach each other's
# image tags. Cleanup policies (auto-deleting old image versions) are
# intentionally not configured here — the storage cost of unpruned images is
# negligible for a thesis project and immutable history of what shipped is
# more valuable than disk savings.
# ----------------------------------------------------------------------------
locals {
  repository_id = "${var.name_prefix}-images-${var.env}"
}

resource "google_artifact_registry_repository" "images" {
  project       = var.project_id
  location      = var.region
  repository_id = local.repository_id
  format        = "DOCKER"
  description   = "Container images for release ${var.name_prefix} (${var.env}) — collector, publisher, and Dataflow Flex Template."

  labels = var.labels
}

# Push images. Granted to Cloud Build (and any future image-promotion job).
resource "google_artifact_registry_repository_iam_member" "writer" {
  for_each = toset(var.writer_sa_emails)

  project    = var.project_id
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${each.value}"
}

# Pull images at runtime. Granted to collector / publisher / Dataflow
# workload SAs.
resource "google_artifact_registry_repository_iam_member" "reader" {
  for_each = toset(var.reader_sa_emails)

  project    = var.project_id
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${each.value}"
}
