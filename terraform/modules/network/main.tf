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
# Custom-mode VPCs (auto_create_subnetworks = false) ship with NO firewall
# rules at all — not even the allow-internal / allow-ssh set that the
# auto-mode "default" network comes with. The only implied behaviour is
# allow-all-egress and deny-all-ingress. So intra-workload connectivity
# has to be granted explicitly; see the Dataflow rule below.
#
# No Cloud NAT — Private Google Access (enabled on the subnet) covers the
# Google APIs our workloads reach, and nothing here needs the public
# internet.
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

# ----------------------------------------------------------------------------
# Dataflow inter-worker firewall rule.
#
# Dataflow workers talk to each other over TCP 12345-12346 (the Beam
# Fn/shuffle harness ports). Because this is a custom-mode VPC with no
# default allow-internal rule (see the header above), that traffic is
# denied by default — and the failure mode is nasty: the job does not
# error, it hangs in "starting"/"running" with workers unable to reach
# each other until it times out an hour later. This rule is exactly the
# fix, and it is the kind of thing that costs an afternoon twice if it is
# missing. It is created unconditionally and deliberately: a disabled or
# absent rule buys nothing (the rule itself is free) and only reintroduces
# that hang, so there is no toggle to get wrong.
#
# Scoped tight: ingress only, source_ranges = the subnet CIDR (not
# 0.0.0.0/0), so only hosts already inside this subnet can reach the
# harness ports. target_tags = "dataflow" is the network tag the Dataflow
# service automatically applies to every worker VM, so the rule matches
# workers without PR 3's launch having to set anything.
# ----------------------------------------------------------------------------
resource "google_compute_firewall" "dataflow_internal" {
  project = var.project_id
  name    = "${var.name_prefix}-allow-dataflow-internal-${var.env}"
  network = google_compute_network.vpc.id

  description = "Allow Dataflow worker-to-worker traffic on the Beam harness ports (TCP 12345-12346), scoped to the subnet CIDR."

  direction     = "INGRESS"
  source_ranges = [google_compute_subnetwork.main.ip_cidr_range]
  target_tags   = ["dataflow"]

  allow {
    protocol = "tcp"
    ports    = ["12345-12346"]
  }
}
