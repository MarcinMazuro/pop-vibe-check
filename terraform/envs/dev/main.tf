locals {
  env = "dev"

  # Project-wide labels applied to every resource that supports them.
  # Kept here (not duplicated in each module call) so the composition root
  # is the single source of truth for environment-wide tagging. The
  # `project` label is the umbrella initiative (repo name), intentionally
  # release-agnostic — `name_prefix` differentiates Clair Obscur from a
  # future Witcher 4 study.
  labels = {
    project    = "pop-vibe-check"
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
    module.iam.publisher_sa_email,
    # dataflow_worker_sa lands with the Dataflow PR; add it here when
    # the iam module gains that workload.
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

module "bigquery" {
  source = "../../modules/bigquery"

  project_id  = var.project_id
  name_prefix = var.name_prefix
  env         = local.env
  region      = var.region
  labels      = local.labels

  publisher_sa_email = module.iam.publisher_sa_email
}

module "pubsub" {
  source = "../../modules/pubsub"

  project_id  = var.project_id
  name_prefix = var.name_prefix
  env         = local.env
  labels      = local.labels

  publisher_sa_email = module.iam.publisher_sa_email
}

module "budgets" {
  source = "../../modules/budgets"

  project_id         = var.project_id
  name_prefix        = var.name_prefix
  env                = local.env
  billing_account_id = var.billing_account_id

  monthly_amount      = var.monthly_budget_amount
  notification_emails = var.notification_emails
}

module "cloud_run_jobs" {
  source = "../../modules/cloud_run_jobs"

  project_id  = var.project_id
  name_prefix = var.name_prefix
  env         = local.env
  region      = var.region
  labels      = local.labels

  raw_archive_bucket_name    = module.storage.raw_archive_bucket_name
  reddit_collector_sa_email  = module.iam.collector_reddit_sa_email
  youtube_collector_sa_email = module.iam.collector_youtube_sa_email
  publisher_sa_email         = module.iam.publisher_sa_email
  secret_names               = module.secrets.secret_names

  bq_dataset_id       = module.bigquery.dataset_id
  bq_landing_table_id = module.bigquery.raw_landing_table_id
  bq_staging_table_id = module.bigquery.raw_staging_table_id
  events_topic_name   = module.pubsub.events_topic_name

  # reddit_image_uri and publisher_image_uri stay on the public 'pause'
  # placeholder until each container is built and pushed — e.g.:
  #   reddit_image_uri    = "${module.artifact_registry.repository_url}/reddit-collector:<sha>"
  #   publisher_image_uri = "${module.artifact_registry.repository_url}/publisher:<sha>"
  youtube_image_uri = "europe-central2-docker.pkg.dev/pop-vibe-check/co-images-dev/youtube-collector:729b1fdc5d8250915d0a59fa68d2408489b0a1f4"
}
