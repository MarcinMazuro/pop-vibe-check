provider "google" {
  project = var.project_id
  region  = var.region
}

# ----------------------------------------------------------------------------
# Project-level GCP API enablements.
#
# Without this, APIs that get auto-disabled by GCP after periods of inactivity
# silently break the next `terraform apply`. Keeping the list declarative
# means any future apply re-enables whatever lapsed.
#
# disable_on_destroy = false   — never turn an API off on a `terraform destroy`
#                                of this config; workload resources elsewhere
#                                may still depend on the API.
# disable_dependent_services = false — guards against an unintended cascade
#                                if a service ever does get disabled.
# ----------------------------------------------------------------------------
resource "google_project_service" "enabled" {
  for_each = var.enabled_services

  project = var.project_id
  service = each.value

  disable_on_destroy         = false
  disable_dependent_services = false
}

locals {
  # Labels applied to every bootstrap resource that supports them.
  # env = "shared" because the state bucket and runner SA are universal
  # across dev/prod and across case studies (they are not release-scoped).
  # project label matches the repository name and is intentionally
  # release-agnostic — name_prefix differentiates releases, the project
  # label keeps the umbrella initiative identifiable.
  labels = {
    project    = "pop-vibe-check"
    env        = "shared"
    owner      = "team-198019-198265-198223"
    managed_by = "terraform"
  }

  # Curated role set for the long-lived Terraform runner SA. Each role is
  # justified by a workload the SA must manage in later configurations.
  # No roles/owner, no roles/editor — those are reserved for the human
  # identity that applies this bootstrap and are revoked afterwards.
  runner_roles = [
    # GCS — raw archive bucket, Cloud Build artifacts bucket, lifecycle
    # rules, and bucket-level IAM bindings.
    "roles/storage.admin",

    # IAM — create per-workload service accounts: collector-reddit,
    # collector-youtube, publisher, dataflow-worker, cloud-build.
    "roles/iam.serviceAccountAdmin",

    # IAM — bind project-level roles to those workload SAs and to Google-
    # managed service agents that need extra permissions.
    "roles/resourcemanager.projectIamAdmin",

    # IAM — actAs the workload SAs when attaching them to Cloud Run Jobs,
    # Dataflow jobs, and Cloud Build. serviceAccountAdmin alone does not
    # grant impersonation.
    "roles/iam.serviceAccountUser",

    # Secret Manager — create empty secret containers and grant
    # secretAccessor to specific workload SAs.
    "roles/secretmanager.admin",

    # Artifact Registry — Docker repository plus reader/writer bindings.
    "roles/artifactregistry.admin",

    # BigQuery — analytics dataset, raw_staging and events tables,
    # authorized views for Looker Studio.
    "roles/bigquery.admin",

    # Pub/Sub — events topic, ordered subscription, dead-letter topic.
    "roles/pubsub.admin",

    # Cloud Run — reddit-collector, youtube-collector, publisher
    # Cloud Run Jobs.
    "roles/run.admin",

    # Dataflow — Flex Template registration and job submission.
    "roles/dataflow.admin",

    # Compute — VPC and subnet with Private Google Access (networkAdmin).
    "roles/compute.networkAdmin",

    # Compute — firewall rules. GCP classes firewall rules as "security"
    # resources, so networkAdmin does not cover them; the Dataflow
    # inter-worker rule (TCP 12345-12346 on the Beam harness ports) needs
    # securityAdmin to create/update/delete.
    "roles/compute.securityAdmin",

    # IAM — custom project roles. Least-privilege grants sometimes have
    # no predefined role that fits: the Dataflow worker needs to manage
    # the internal subscription Dataflow creates to track a watermark
    # from a custom Pub/Sub timestamp attribute, and the only predefined
    # role covering it is roles/pubsub.editor over the whole project.
    # roleAdmin lets the pubsub module define that capability exactly,
    # instead of over-granting to avoid a custom role.
    "roles/iam.roleAdmin",

    # Cloud Build — per-service triggers scoped by included_files.
    "roles/cloudbuild.builds.editor",

    # Cloud Monitoring — notification channels for budget alerts, plus
    # any future alert policies / uptime checks. Editor (not admin)
    # covers create/update/delete on channels and policies without
    # granting access to enable destructive admin-only ops.
    "roles/monitoring.editor",

    # Vertex AI — Model Registry, Endpoints, and the Workbench instance
    # used to fine-tune DistilBERT. Admin (not user) because this SA
    # creates and destroys those resources, not merely predicts.
    "roles/aiplatform.admin",

    # Vertex AI Workbench (notebooks.googleapis.com) — google_workbench_instance
    # is a GCE VM with a Jupyter service; notebooks.admin covers the
    # Workbench control plane. instanceAdmin.v1 is required as well
    # because the instance is a Compute Engine VM (disks, accelerators,
    # start/stop) and notebooks.admin does not include compute.instances.*.
    "roles/notebooks.admin",
    "roles/compute.instanceAdmin.v1",

    # Service Usage — google_project_service resources enable APIs
    # idempotently; without this, a re-apply on a fresh project would fail
    # even after APIs were turned on by hand during bootstrap.
    "roles/serviceusage.serviceUsageAdmin",
  ]
}

# ----------------------------------------------------------------------------
# Universal remote state bucket.
#
# One bucket holds Terraform state for every environment and every case
# study in this repo. Separation happens via GCS object prefix in the
# backend block of each composition (envs/dev/ uses prefix "dev/", a
# future envs/dev-w4/ would use "dev-w4/", and so on).
#
# Versioning is non-negotiable: state corruption recovery depends on it.
# Uniform bucket-level access blocks legacy ACLs. Public access prevention is
# enforced because state contains resource IDs and (in some providers) tokens.
# No lifecycle rule — state is retained forever.
# ----------------------------------------------------------------------------
resource "google_storage_bucket" "tf_state" {
  name     = "${var.name_prefix}-tf-state"
  location = var.region
  project  = var.project_id

  # Without storage.googleapis.com enabled, this resource cannot be
  # created. Terraform's graph cannot infer this dependency.
  depends_on = [google_project_service.enabled]

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy_state_bucket

  versioning {
    enabled = true
  }

  labels = local.labels
}

# ----------------------------------------------------------------------------
# Long-lived Terraform runner service account.
#
# Shared across every environment and every case study, paired with the
# universal state bucket above. Cloud Build will impersonate this SA later
# via an iam.serviceAccountTokenCreator binding (added when the cloud_build
# module lands). The runner SA itself is created here so its identity is
# stable across every later apply. google_service_account does not support
# labels in provider v5.
# ----------------------------------------------------------------------------
resource "google_service_account" "tf_runner" {
  project      = var.project_id
  account_id   = "${var.name_prefix}-tf-runner-sa"
  display_name = "Terraform runner (long-lived)"
  description  = "Applies Terraform for every config except terraform/bootstrap. Impersonated by Cloud Build."

  # Wait for the IAM API to be enabled before attempting SA creation.
  # Terraform's dependency graph cannot infer this automatically.
  depends_on = [google_project_service.enabled]
}

resource "google_project_iam_member" "tf_runner_roles" {
  for_each = toset(local.runner_roles)

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.tf_runner.email}"
}

# ----------------------------------------------------------------------------
# Operator impersonation grants.
#
# Lets each listed human identity impersonate the runner SA so envs/*/
# applies can use provider-level impersonation without a per-operator
# manual gcloud add-iam-policy-binding. Owner does NOT cover this — GCP
# intentionally excludes iam.serviceAccounts.getAccessToken from
# roles/owner so an Owner cannot silently impersonate every SA. Empty
# operator_emails skips the resources entirely; falls back to manual
# grants documented in the README.
# ----------------------------------------------------------------------------
resource "google_service_account_iam_member" "operator_token_creator" {
  for_each = toset(var.operator_emails)

  service_account_id = google_service_account.tf_runner.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "user:${each.value}"
}

# ----------------------------------------------------------------------------
# Budgets live on the billing account, not the project. Granting
# costsManager at billing-account level is the minimum needed to create
# google_billing_budget resources. Skipped when billing_account_id is
# empty; budgets must then be applied with a human identity.
# ----------------------------------------------------------------------------
resource "google_billing_account_iam_member" "tf_runner_billing" {
  count = var.billing_account_id == "" ? 0 : 1

  billing_account_id = var.billing_account_id
  role               = "roles/billing.costsManager"
  member             = "serviceAccount:${google_service_account.tf_runner.email}"
}
