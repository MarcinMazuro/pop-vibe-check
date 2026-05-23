# ----------------------------------------------------------------------------
# VPC + single regional subnet.
#
# Used by Dataflow workers (Phase 1, mandatory — Dataflow jobs always run
# in a specified network) and optionally by Cloud Run Jobs that opt into
# Direct VPC egress. Collectors that stick with default Cloud Run egress
# don't strictly need this network, but every Phase 1 streaming
# component does.
#
# auto_create_subnetworks = false so the only subnet is the one declared
# explicitly below — no surprise subnets in unused regions.
#
# No Cloud NAT, no firewall rules beyond the default implicit allow-egress
# / allow-internal of a fresh VPC. Add only what specific workloads need
# when they land.
#
# google_compute_network and google_compute_subnetwork do not support
# labels in provider v5 — documented exception from the project-wide
# labelling convention.
# ----------------------------------------------------------------------------
resource "google_compute_network" "vpc" {
  project                 = var.project_id
  name                    = "${var.name_prefix}-vpc-${var.env}"
  auto_create_subnetworks = false
  description             = "Shared VPC for release ${var.name_prefix} (${var.env}). Hosts Dataflow workers and any Cloud Run service that opts into Direct VPC egress."
}

resource "google_compute_subnetwork" "main" {
  project       = var.project_id
  name          = "${var.name_prefix}-subnet-${var.env}"
  region        = var.region
  network       = google_compute_network.vpc.id
  ip_cidr_range = var.subnet_cidr

  # Private Google Access lets workloads in this subnet reach Google APIs
  # (Secret Manager, GCS, BigQuery, Pub/Sub, ...) via the internal Google
  # backbone instead of public internet — no external IP needed on a
  # Dataflow worker or Cloud Run task.
  private_ip_google_access = true
}
