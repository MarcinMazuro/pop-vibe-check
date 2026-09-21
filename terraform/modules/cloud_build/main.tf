# ----------------------------------------------------------------------------
# Cloud Build CI/CD for one environment.
#
# Three layers, created in two applies:
#
#   1. Always: the secret containers CI reads (GitHub token, env tfvars),
#      their accessor grants, log-writer and approver grants.
#   2. Once github_app_installation_id is set and the token secret has a
#      version: the GitHub (2nd gen) connection and the linked repository.
#   3. Hanging off that repository: the triggers.
#
# The two-apply shape is forced by GitHub, not Terraform: the connection
# cannot be created until someone installs the Cloud Build GitHub App and
# stores a token, and neither can be done from Terraform. See README.md.
#
# Two identities run the builds:
#   - cloud_build_sa_email — image builds, tests, image/template deploys;
#   - terraform_ci_sa_email — terraform plan/apply, impersonating the
#     runner SA. Created in terraform/bootstrap.
# ----------------------------------------------------------------------------

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  github_enabled = var.github_app_installation_id != null

  cloud_build_service_agent = "service-${data.google_project.this.number}@gcp-sa-cloudbuild.iam.gserviceaccount.com"

  cloud_build_sa_id  = "projects/${var.project_id}/serviceAccounts/${var.cloud_build_sa_email}"
  terraform_ci_sa_id = "projects/${var.project_id}/serviceAccounts/${var.terraform_ci_sa_email}"

  # Builds from forks wait for a collaborator's `/gcbrun` comment; the repo
  # is public, and a PR build runs arbitrary Dockerfiles and tests.
  pr_comment_control = "COMMENTS_ENABLED_FOR_EXTERNAL_CONTRIBUTORS_ONLY"

  # Container images built from this repo. Each is built (never pushed) on
  # pull requests and built, pushed and deployed on merge to main.
  #
  # included_files follows each Dockerfile's COPY lines, not just the
  # service directory — the collectors and the publisher both bake in
  # collectors/common and collectors/config, and the pipeline image bakes
  # in nlp/. Paths the Dockerfiles delete again (tests, notebooks,
  # training) are ignored so they do not trigger a rebuild.
  images = {
    youtube-collector = {
      filename = "collectors/youtube/cloudbuild.yaml"
      included_files = [
        "collectors/__init__.py",
        "collectors/common/**",
        "collectors/config/**",
        "collectors/youtube/**",
      ]
      ignored_files = ["**/*.md", "**/tests/**"]
      substitutions = {
        _JOB = var.youtube_job_name
      }
    }
    publisher = {
      filename = "publisher/cloudbuild.yaml"
      included_files = [
        "collectors/__init__.py",
        "collectors/common/**",
        "collectors/config/**",
        "publisher/**",
      ]
      ignored_files = ["**/*.md", "**/tests/**"]
      substitutions = {
        _JOB = var.publisher_job_name
      }
    }
    sentiment-pipeline = {
      filename       = "dataflow/cloudbuild.yaml"
      included_files = ["dataflow/**", "nlp/**"]
      ignored_files = [
        "**/*.md",
        "**/tests/**",
        "dataflow/*.sh",
        "dataflow/*.sql",
        # The replay pipeline's own config: it orchestrates the image,
        # it is not part of it.
        "dataflow/replay.cloudbuild.yaml",
        "nlp/eval/**",
        "nlp/notebooks/**",
        "nlp/tracking/**",
        "nlp/training/**",
      ]
      substitutions = {
        _TEMPLATE_SPEC_DIR = var.template_spec_dir
      }
    }
  }

  image_common_substitutions = {
    _REGION = var.region
    _REPO   = var.artifact_registry_repository_id
  }
}

# ----------------------------------------------------------------------------
# Secret containers. Values are added out of band with
# `gcloud secrets versions add`, never through Terraform state.
# ----------------------------------------------------------------------------

# GitHub personal access token (classic, scopes: repo + read:user). Cloud
# Build uses it to authorize the connection; the GitHub App installation
# does the rest.
resource "google_secret_manager_secret" "github_token" {
  project   = var.project_id
  secret_id = "${var.name_prefix}-github-token-${var.env}"

  replication {
    auto {}
  }

  labels = var.labels
}

# Only the Cloud Build service agent reads the token — builds never see it.
resource "google_secret_manager_secret_iam_member" "github_token_service_agent" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.github_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.cloud_build_service_agent}"
}

# The environment's canonical terraform.tfvars. Kept out of git because the
# repository is public (billing account, alert recipients) and because one
# shared copy stops operators applying with diverging local files.
resource "google_secret_manager_secret" "tfvars" {
  project   = var.project_id
  secret_id = "${var.name_prefix}-tfvars-${var.env}"

  replication {
    auto {}
  }

  labels = var.labels
}

resource "google_secret_manager_secret_iam_member" "tfvars_terraform_ci" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.tfvars.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.terraform_ci_sa_email}"
}

# ----------------------------------------------------------------------------
# Build identity and approvers.
# ----------------------------------------------------------------------------

# A build running as a user-specified SA needs this to write its logs; the
# build configs use CLOUD_LOGGING_ONLY. The Terraform CI SA gets the same
# grant in bootstrap, next to where it is created.
resource "google_project_iam_member" "cloud_build_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${var.cloud_build_sa_email}"
}

# Who can release a queued `terraform apply`.
resource "google_project_iam_member" "approver" {
  for_each = toset(var.approver_emails)

  project = var.project_id
  role    = "roles/cloudbuild.builds.approver"
  member  = "user:${each.value}"
}

# ----------------------------------------------------------------------------
# GitHub connection (2nd gen) and repository.
# ----------------------------------------------------------------------------
resource "google_cloudbuildv2_connection" "github" {
  count = local.github_enabled ? 1 : 0

  project  = var.project_id
  location = var.region
  name     = "${var.name_prefix}-github-${var.env}"

  github_config {
    app_installation_id = var.github_app_installation_id

    authorizer_credential {
      oauth_token_secret_version = "${google_secret_manager_secret.github_token.id}/versions/latest"
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.github_token_service_agent]
}

resource "google_cloudbuildv2_repository" "this" {
  count = local.github_enabled ? 1 : 0

  project           = var.project_id
  location          = var.region
  name              = var.github_repo
  parent_connection = google_cloudbuildv2_connection.github[0].name
  remote_uri        = "https://github.com/${var.github_owner}/${var.github_repo}.git"
}

# ----------------------------------------------------------------------------
# Python checks — ruff, black, pytest on every pull request touching Python.
# ----------------------------------------------------------------------------
resource "google_cloudbuild_trigger" "python_checks_pr" {
  count = local.github_enabled ? 1 : 0

  project         = var.project_id
  location        = var.region
  name            = "${var.name_prefix}-python-checks-pr-${var.env}"
  description     = "PR: ruff, black --check and pytest across every Python package."
  filename        = "cloudbuild.checks.yaml"
  service_account = local.cloud_build_sa_id

  included_files = [
    "**/*.py",
    "pyproject.toml",
    "requirements-dev.txt",
    "collectors/config/**",
    "cloudbuild.checks.yaml",
  ]

  repository_event_config {
    repository = google_cloudbuildv2_repository.this[0].id
    pull_request {
      branch          = "^main$"
      comment_control = local.pr_comment_control
    }
  }
}

# ----------------------------------------------------------------------------
# Container images.
# ----------------------------------------------------------------------------
resource "google_cloudbuild_trigger" "image_pr" {
  for_each = { for k, v in local.images : k => v if local.github_enabled }

  project         = var.project_id
  location        = var.region
  name            = "${var.name_prefix}-${each.key}-pr-${var.env}"
  description     = "PR: build the ${each.key} image without pushing it."
  filename        = each.value.filename
  service_account = local.cloud_build_sa_id
  included_files  = each.value.included_files
  ignored_files   = each.value.ignored_files

  substitutions = merge(local.image_common_substitutions, each.value.substitutions, {
    _DEPLOY = "false"
  })

  repository_event_config {
    repository = google_cloudbuildv2_repository.this[0].id
    pull_request {
      branch          = "^main$"
      comment_control = local.pr_comment_control
    }
  }
}

resource "google_cloudbuild_trigger" "image_deploy" {
  for_each = { for k, v in local.images : k => v if local.github_enabled }

  project         = var.project_id
  location        = var.region
  name            = "${var.name_prefix}-${each.key}-deploy-${var.env}"
  description     = "main: build, push and deploy the ${each.key} image."
  filename        = each.value.filename
  service_account = local.cloud_build_sa_id
  included_files  = each.value.included_files
  ignored_files   = each.value.ignored_files

  substitutions = merge(local.image_common_substitutions, each.value.substitutions, {
    _DEPLOY = "true"
  })

  repository_event_config {
    repository = google_cloudbuildv2_repository.this[0].id
    push {
      branch = "^main$"
    }
  }
}

# ----------------------------------------------------------------------------
# Terraform — plan on pull requests, apply on main behind an approval.
#
# Approval is requested before the build starts, so the apply build plans
# again against current state and applies that plan. Its log shows exactly
# what was applied; the PR plan is what reviewers approve in principle.
# ----------------------------------------------------------------------------
locals {
  terraform_substitutions = {
    _ENV_DIR       = var.terraform_env_dir
    _TFVARS_SECRET = google_secret_manager_secret.tfvars.secret_id
    _RUNNER_SA     = var.terraform_runner_sa_email
  }

  terraform_included_files = ["terraform/**"]
}

resource "google_cloudbuild_trigger" "terraform_plan_pr" {
  count = local.github_enabled ? 1 : 0

  project         = var.project_id
  location        = var.region
  name            = "${var.name_prefix}-terraform-plan-pr-${var.env}"
  description     = "PR: terraform fmt, validate and plan for ${var.terraform_env_dir}."
  filename        = "terraform/cloudbuild.yaml"
  service_account = local.terraform_ci_sa_id
  included_files  = local.terraform_included_files

  substitutions = merge(local.terraform_substitutions, { _MODE = "plan" })

  repository_event_config {
    repository = google_cloudbuildv2_repository.this[0].id
    pull_request {
      branch          = "^main$"
      comment_control = local.pr_comment_control
    }
  }
}

resource "google_cloudbuild_trigger" "terraform_apply" {
  count = local.github_enabled ? 1 : 0

  project         = var.project_id
  location        = var.region
  name            = "${var.name_prefix}-terraform-apply-${var.env}"
  description     = "main: terraform apply for ${var.terraform_env_dir}, after manual approval."
  filename        = "terraform/cloudbuild.yaml"
  service_account = local.terraform_ci_sa_id
  included_files  = local.terraform_included_files

  substitutions = merge(local.terraform_substitutions, { _MODE = "apply" })

  approval_config {
    approval_required = true
  }

  repository_event_config {
    repository = google_cloudbuildv2_repository.this[0].id
    push {
      branch = "^main$"
    }
  }
}

# ----------------------------------------------------------------------------
# Replay pipeline — manual trigger.
#
# One button that launches Dataflow, runs the publisher, waits for the
# pipeline to catch up, drains, promotes and fingerprints. Manual, not
# event-driven: a replay starts a streaming job that bills until drained,
# and nobody wants a push to main to do that.
#
#   gcloud builds triggers run co-replay-dev --region=europe-central2 \
#     --branch=main --substitutions=_MODEL=stub
#
# The infrastructure values below come from the same Terraform outputs a
# laptop run of dataflow/launch.sh reads; Cloud Build has no state to read
# them from, so they are baked into the trigger. That includes the Vertex
# Endpoint, so `--substitutions=_MODEL=vertex` is all a real-model replay
# needs; the values are empty while no Endpoint exists.
# ----------------------------------------------------------------------------
resource "google_cloudbuild_trigger" "replay" {
  count = local.github_enabled ? 1 : 0

  project         = var.project_id
  location        = var.region
  name            = "${var.name_prefix}-replay-${var.env}"
  description     = "Manual: one full replay (launch, publish, drain, promote, fingerprint)."
  service_account = local.cloud_build_sa_id

  source_to_build {
    repository = google_cloudbuildv2_repository.this[0].id
    ref        = "refs/heads/main"
    repo_type  = "GITHUB"
  }

  git_file_source {
    repository = google_cloudbuildv2_repository.this[0].id
    path       = "dataflow/replay.cloudbuild.yaml"
    revision   = "refs/heads/main"
    repo_type  = "GITHUB"
  }

  substitutions = {
    _REGION                  = var.region
    _WORKER_SA               = var.dataflow_worker_sa_email
    _SUBNETWORK              = var.dataflow_subnetwork
    _TEMP_LOCATION           = var.dataflow_temp_location
    _STAGING_LOCATION        = var.dataflow_staging_location
    _TEMPLATE_SPEC_DIR       = var.template_spec_dir
    _INPUT_SUBSCRIPTION      = var.dataflow_input_subscription
    _OUTPUT_TABLE            = var.dataflow_events_landing_table
    _DLQ_TOPIC               = var.dataflow_dlq_topic
    _PUBLISHER_JOB           = var.publisher_job_name
    _VERTEX_ENDPOINT_ID      = var.vertex_endpoint_id
    _VERTEX_PROJECT          = var.vertex_project
    _VERTEX_LOCATION         = var.vertex_location
    _DATASET                 = var.bq_dataset_id
    _RAW_STAGING_TABLE_ID    = var.raw_staging_table_id
    _EVENTS_LANDING_TABLE_ID = var.events_landing_table_id
    _EVENTS_TABLE_ID         = var.events_table_id
  }
}
