locals {
  env = "dev"

  # Project-wide labels applied to every resource that supports them.
  # Kept here (not duplicated in each module call) so the composition root
  # is the single source of truth for environment-wide tagging.
  labels = {
    project    = "co-sentiment"
    env        = local.env
    owner      = "team-198019-198265-198223"
    managed_by = "terraform"
  }
}

module "storage" {
  source = "../../modules/storage"

  name_prefix = var.name_prefix
  env         = local.env
  region      = var.region
  labels      = local.labels

  # Raw archive grows indefinitely in dev; flip to a positive number
  # before a tear-down if you want Terraform to clean up the bucket
  # contents on the next apply.
  raw_archive_autodelete_days = 0
}

module "iam" {
  source = "../../modules/iam"

  project_id  = var.project_id
  name_prefix = var.name_prefix
  env         = local.env
}

module "secrets" {
  source = "../../modules/secrets"

  project_id  = var.project_id
  name_prefix = var.name_prefix
  env         = local.env
  labels      = local.labels

  collector_reddit_sa_email  = module.iam.collector_reddit_sa_email
  collector_youtube_sa_email = module.iam.collector_youtube_sa_email
}

module "artifact_registry" {
  source = "../../modules/artifact_registry"

  project_id  = var.project_id
  name_prefix = var.name_prefix
  env         = local.env
  region      = var.region
  labels      = local.labels

  writer_sa_emails = [
    module.iam.cloud_build_sa_email,
  ]

  reader_sa_emails = [
    module.iam.collector_reddit_sa_email,
    module.iam.collector_youtube_sa_email,
    # publisher_sa and dataflow_worker_sa land in Phase 1; add them here
    # when the iam module gains those workloads.
  ]
}

module "network" {
  source = "../../modules/network"

  project_id  = var.project_id
  name_prefix = var.name_prefix
  env         = local.env
  region      = var.region

  # Default /24 is plenty; override only if a workload needs more IPs
  # than ~250.
  # subnet_cidr = "10.10.0.0/24"
}
