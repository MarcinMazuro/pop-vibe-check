output "network_id" {
  description = "Fully-qualified VPC resource ID. Use when a downstream resource references the network by ID (most google_compute_* args)."
  value       = google_compute_network.vpc.id
}

output "network_self_link" {
  description = "Self-link URL of the VPC. Used by Dataflow job submissions (the `network` field expects this format)."
  value       = google_compute_network.vpc.self_link
}

output "network_name" {
  description = "Short VPC name (e.g. 'co-vpc-dev')."
  value       = google_compute_network.vpc.name
}

output "subnet_id" {
  description = "Fully-qualified subnet resource ID."
  value       = google_compute_subnetwork.main.id
}

output "subnet_self_link" {
  description = "Self-link URL of the subnet. Used by Dataflow (the `subnetwork` field) and by Cloud Run Direct VPC egress configs."
  value       = google_compute_subnetwork.main.self_link
}

output "subnet_name" {
  description = "Short subnet name (e.g. 'co-subnet-dev')."
  value       = google_compute_subnetwork.main.name
}

output "subnet_cidr" {
  description = "Primary CIDR of the subnet. Handy for scoping downstream firewall rules to in-subnet traffic."
  value       = google_compute_subnetwork.main.ip_cidr_range
}

output "dataflow_worker_tag" {
  description = "Network tag the Dataflow inter-worker firewall rule targets. Dataflow auto-applies this tag to worker VMs, so the intra-worker allow rule matches them without extra launch config. Exposed so the dataflow module references one string instead of duplicating the literal."
  value       = one(google_compute_firewall.dataflow_internal.target_tags)
}
