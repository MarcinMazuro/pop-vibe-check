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

  # Worker SA gets objectAdmin on the dataflow-temp bucket (staging/temp
  # writes). The binding lives in the storage module, next to the bucket.
  dataflow_worker_sa_email = module.iam.dataflow_worker_sa_email

  # Trainer SA writes dataset caches / MLflow runs under nlp/ on the
  # artifacts bucket. The binding lives next to the bucket.
  ml_trainer_sa_email = module.iam.ml_trainer_sa_email

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
    # Literal: module.iam.ml_trainer_sa_email is computed and would make
    # this for_each set unplannable. Account id is deterministic.
    "${var.name_prefix}-ml-trainer-sa-${local.env}@${var.project_id}.iam.gserviceaccount.com",
  ]

  reader_sa_emails = [
    module.iam.collector_reddit_sa_email,
    module.iam.collector_youtube_sa_email,
    module.iam.publisher_sa_email,
    # Dataflow workers pull the Flex Template image at launch; no public
    # IPs, so they read Artifact Registry over Private Google Access.
    #
    # Built as a literal, not module.iam.dataflow_worker_sa_email: that
    # output is the *new* SA's computed .email, unknown at plan time, and
    # an unknown value in this reader for_each set makes the whole set
    # unplannable ("Invalid for_each argument"). The account_id is
    # deterministic, so the email is known here; depends_on below still
    # orders the SA's creation before this grant.
    "${var.name_prefix}-dataflow-worker-sa-${local.env}@${var.project_id}.iam.gserviceaccount.com",
  ]

  # The dataflow-worker reader entry above is a literal string, so it
  # carries no implicit dependency on the SA resource. Order the whole iam
  # module (which creates that SA) ahead of these grants explicitly.
  depends_on = [module.iam]
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

  publisher_sa_email       = module.iam.publisher_sa_email
  dataflow_worker_sa_email = module.iam.dataflow_worker_sa_email
  ml_trainer_sa_email      = module.iam.ml_trainer_sa_email
}

module "pubsub" {
  source = "../../modules/pubsub"

  project_id  = var.project_id
  name_prefix = var.name_prefix
  env         = local.env
  labels      = local.labels

  publisher_sa_email       = module.iam.publisher_sa_email
  dataflow_worker_sa_email = module.iam.dataflow_worker_sa_email
}

module "dataflow" {
  source = "../../modules/dataflow"

  project_id = var.project_id
  region     = var.region

  dataflow_worker_sa_email = module.iam.dataflow_worker_sa_email

  # The launcher is the Cloud Build SA — the roadmap's eventual CI launcher
  # of Flex Template jobs. A manual dev launch impersonates it (see the
  # dataflow module README), the same way applies impersonate the runner SA.
  launcher_sa_email = module.iam.cloud_build_sa_email

  # Launch parameters, composed from the modules that own each resource.
  subnetwork_self_link     = module.network.subnet_self_link
  network_self_link        = module.network.network_self_link
  worker_network_tag       = module.network.dataflow_worker_tag
  dataflow_temp_bucket_url = module.storage.dataflow_temp_bucket_url
  bq_dataset_id            = module.bigquery.dataset_id
  events_landing_table_id  = module.bigquery.events_landing_table_id
  events_table_id          = module.bigquery.events_table_id
  dataflow_subscription_id = module.pubsub.dataflow_subscription_id
  dlq_topic_id             = module.pubsub.dlq_topic_id
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

  # reddit_image_uri stays on the public 'pause' placeholder until the
  # Reddit container is built and pushed — e.g.:
  #   reddit_image_uri = "${module.artifact_registry.repository_url}/reddit-collector:<sha>"
  youtube_image_uri   = "europe-central2-docker.pkg.dev/pop-vibe-check/co-images-dev/youtube-collector:729b1fdc5d8250915d0a59fa68d2408489b0a1f4"
  publisher_image_uri = "europe-central2-docker.pkg.dev/pop-vibe-check/co-images-dev/publisher:2e209f7c654dca317b49a4afeb4d2b402193846e"
}

# Vertex AI Workbench + Endpoint for DistilBERT. Both gates default OFF
# (count = 0) so a routine apply does not start a GPU — the same shape
# reddit_image_uri uses to keep the Reddit job on a placeholder. Flip
# enable_nlp_workbench / enable_nlp_endpoint via -var for a training or
# serving session; see terraform/modules/vertex_nlp/README.md.
module "vertex_nlp" {
  source = "../../modules/vertex_nlp"

  project_id  = var.project_id
  name_prefix = var.name_prefix
  env         = local.env
  region      = var.region
  labels      = local.labels

  trainer_sa_email         = module.iam.ml_trainer_sa_email
  dataflow_worker_sa_email = module.iam.dataflow_worker_sa_email
  network_id               = module.network.network_id
  subnet_id                = module.network.subnet_id

  enable_workbench        = var.enable_nlp_workbench
  workbench_desired_state = var.nlp_workbench_desired_state
  workbench_owners        = var.nlp_workbench_owners
  enable_endpoint         = var.enable_nlp_endpoint
}
