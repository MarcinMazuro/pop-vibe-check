# ----------------------------------------------------------------------------
# Production composition.
#
# Same modules as envs/dev, wired the same way, with three deliberate
# differences:
#
#   1. No cloud_build module. CI/CD is dev-only for now: the GitHub
#      connection, the image triggers and the approval-gated apply all
#      point at dev. prod is applied by an operator, which is also what
#      makes it the reproducibility demonstration — the whole environment
#      stands up from committed code in one apply.
#   2. No vertex_nlp module. Training and model serving happen in dev; a
#      prod replay would call the dev Endpoint or run the stub. Keeping a
#      second Endpoint idle here would bill for nothing.
#   3. Jobs start on the public `pause` placeholder image, because the
#      image triggers that deploy real ones are dev-only. Point the
#      *_image_uri variables at an Artifact Registry digest to run them.
#
# Everything else — buckets, dataset, tables, topics, subscriptions,
# service accounts, secrets, network, alerts, budget — is identical in
# shape to dev, under the `prod` suffix.
# ----------------------------------------------------------------------------

locals {
  env = "prod"

  # Project-wide labels applied to every resource that supports them.
  # Kept here (not duplicated in each module call) so the composition root
  # is the single source of truth for environment-wide tagging. The
  # `project` label is the umbrella initiative (repo name), intentionally
  # release-agnostic — `name_prefix` differentiates Clair Obscur from a
  # future Witcher 4 study.
  # Workload SA emails, composed rather than read from module.iam: see the
  # artifact_registry block for why a computed email cannot appear in a
  # for_each set.
  sa_emails = {
    for workload in [
      "collector-reddit",
      "collector-youtube",
      "collector-steam",
      "publisher",
      "cloud-build",
      "dataflow-worker",
      "ml-trainer",
    ] :
    workload => "${var.name_prefix}-${workload}-sa-${local.env}@${var.project_id}.iam.gserviceaccount.com"
  }

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
  # artifacts bucket. The binding lives next to the bucket. Training
  # happens in dev; the binding exists so the bucket's IAM is identical.
  ml_trainer_sa_email = module.iam.ml_trainer_sa_email

  # The archive is the durable copy of what the internet said; it is never
  # swept on a schedule. Flip to a positive number only before a
  # deliberate tear-down.
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
  collector_steam_sa_email   = module.iam.collector_steam_sa_email
}

module "artifact_registry" {
  source = "../../modules/artifact_registry"

  project_id  = var.project_id
  name_prefix = var.name_prefix
  env         = local.env
  region      = var.region
  labels      = local.labels

  # Every entry is a literal. In prod nothing exists yet, so each SA email
  # is computed in this same apply, and an unknown value anywhere in a
  # for_each set makes the whole set unplannable ("Invalid for_each
  # argument"). Account ids are deterministic, so the emails are known
  # here; depends_on below still orders the SAs ahead of these grants.
  writer_sa_emails = [
    local.sa_emails["cloud-build"],
    local.sa_emails["ml-trainer"],
  ]

  reader_sa_emails = [
    local.sa_emails["collector-reddit"],
    local.sa_emails["collector-youtube"],
    local.sa_emails["collector-steam"],
    local.sa_emails["publisher"],
    # Dataflow workers pull the Flex Template image at launch; no public
    # IPs, so they read Artifact Registry over Private Google Access.
    local.sa_emails["dataflow-worker"],
  ]

  depends_on = [module.iam]
}

module "network" {
  source = "../../modules/network"

  project_id  = var.project_id
  name_prefix = var.name_prefix
  env         = local.env
  region      = var.region

  # A different range from dev's 10.10.0.0/24: the two VPCs are separate
  # today, and non-overlapping ranges keep peering or a shared VPC from
  # being a migration rather than a configuration change.
  subnet_cidr = "10.20.0.0/24"
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

  # Dashboard readers get the reporting views and nothing else.
  report_viewer_emails = var.report_viewer_emails
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

  # The launcher identity. dev's replay pipeline runs as this SA; in prod
  # a launch is manual and impersonates it, so the permissions a launch
  # needs are described in code either way.
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

  # Ordering, not data: a job's secret_key_ref is validated by Cloud Run at
  # create time, so the workload SA must already hold secretAccessor on the
  # secret. Passing secret_names carries no dependency on the accessor
  # bindings, and without this the Steam job's creation lost that race
  # ("Permission denied on secret ... for Revision service account").
  depends_on = [module.secrets]

  project_id  = var.project_id
  name_prefix = var.name_prefix
  env         = local.env
  region      = var.region
  labels      = local.labels

  raw_archive_bucket_name    = module.storage.raw_archive_bucket_name
  reddit_collector_sa_email  = module.iam.collector_reddit_sa_email
  youtube_collector_sa_email = module.iam.collector_youtube_sa_email
  steam_collector_sa_email   = module.iam.collector_steam_sa_email
  publisher_sa_email         = module.iam.publisher_sa_email
  secret_names               = module.secrets.secret_names

  bq_dataset_id       = module.bigquery.dataset_id
  bq_landing_table_id = module.bigquery.raw_landing_table_id
  bq_staging_table_id = module.bigquery.raw_staging_table_id
  events_topic_name   = module.pubsub.events_topic_name

  # Images seed a freshly created job and are then ignored by the module.
  # There are no prod image triggers yet, so these stay on the `pause`
  # placeholder until someone points them at a digest — a dev image works,
  # the registry is per-env but readable within the project.
  youtube_image_uri   = var.youtube_image_uri
  steam_image_uri     = var.steam_image_uri
  publisher_image_uri = var.publisher_image_uri
}

# Alert policies for the streaming path: job failure, a job left running
# (the cost guard), an ageing replay backlog, and dead-lettered records.
# Notification channels come from the budgets module so alerts reach the
# same recipients as budget notifications.
module "monitoring" {
  source = "../../modules/monitoring"

  project_id  = var.project_id
  name_prefix = var.name_prefix
  env         = local.env
  region      = var.region

  notification_channel_ids = values(module.budgets.notification_channel_ids)

  dataflow_subscription_name = module.pubsub.dataflow_subscription_name
  dlq_subscription_name      = module.pubsub.dlq_subscription_name

  max_job_runtime_hours     = var.dataflow_max_job_runtime_hours
  backlog_age_alert_seconds = var.replay_backlog_age_alert_seconds
}
