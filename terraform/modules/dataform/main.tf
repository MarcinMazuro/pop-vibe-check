# ----------------------------------------------------------------------------
# Dataform repository for the reporting layer.
#
# The SQL lives in this git repository's root (workflow_settings.yaml,
# definitions/, includes/) — managed Dataform reads a project from the
# repository root only, not a subdirectory. Dataform here is a window onto
# GitHub: the web IDE edits branches through it, and Cloud Build compiles
# main at the merged commit and runs the result (cloudbuild.dataform.yaml).
# There is no release or workflow config: views change when code does, not
# on a schedule.
#
# Identities:
#   - the Dataform service agent (Google-managed) fetches from GitHub with
#     the token below and mints tokens for the Dataform SA;
#   - the Dataform SA (iam module) runs every invocation — its BigQuery
#     grants live in modules/bigquery, next to the datasets;
#   - the deployer (Cloud Build) and the web IDE editors start invocations,
#     which under strict act-as needs actAs on the Dataform SA.
# ----------------------------------------------------------------------------

data "google_project" "this" {
  project_id = var.project_id
}

locals {
  service_agent_email = "service-${data.google_project.this.number}@gcp-sa-dataform.iam.gserviceaccount.com"

  dataform_sa_id = "projects/${var.project_id}/serviceAccounts/${var.dataform_sa_email}"
}

# The service agent is otherwise created with the first repository, which
# is too late for the grants below that the repository needs to work.
resource "google_project_service_identity" "dataform" {
  provider = google-beta

  project = var.project_id
  service = "dataform.googleapis.com"
}

# ----------------------------------------------------------------------------
# GitHub token. A fine-grained PAT on this one repository with
# contents: read/write (write lets web IDE workspaces push branches). The
# value is added out of band with `gcloud secrets versions add`, never
# through Terraform state.
# ----------------------------------------------------------------------------
resource "google_secret_manager_secret" "github_token" {
  project   = var.project_id
  secret_id = "${var.name_prefix}-dataform-github-token-${var.env}"

  replication {
    auto {}
  }

  labels = var.labels
}

resource "google_secret_manager_secret_iam_member" "github_token_service_agent" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.github_token.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${local.service_agent_email}"

  depends_on = [google_project_service_identity.dataform]
}

resource "google_service_account_iam_member" "service_agent_token_creator" {
  service_account_id = local.dataform_sa_id
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${local.service_agent_email}"

  depends_on = [google_project_service_identity.dataform]
}

# ----------------------------------------------------------------------------
# Repository.
#
# A workspace compiles with its name as a dataset suffix, so running
# anything from the web IDE writes co_reporting_dev_<workspace> and never
# touches the views the dashboard reads. Workspace names therefore have to
# be valid in a dataset ID: letters, digits and underscores.
# ----------------------------------------------------------------------------
resource "google_dataform_repository" "this" {
  provider = google-beta

  project      = var.project_id
  region       = var.region
  name         = "${var.name_prefix}-reporting-${var.env}"
  display_name = "${var.name_prefix} reporting (${var.env})"

  service_account = var.dataform_sa_email

  git_remote_settings {
    url                                 = "https://github.com/${var.github_owner}/${var.github_repo}.git"
    default_branch                      = var.default_branch
    authentication_token_secret_version = "${google_secret_manager_secret.github_token.id}/versions/latest"
  }

  workspace_compilation_overrides {
    schema_suffix = "$${workspaceName}"
  }

  labels = var.labels

  depends_on = [
    google_secret_manager_secret_iam_member.github_token_service_agent,
    google_service_account_iam_member.service_agent_token_creator,
  ]
}

# ----------------------------------------------------------------------------
# Who may start invocations: the Cloud Build deployer and the web IDE
# editors. dataform.editor covers compilation results, workflow
# invocations and workspaces on this repository only; actAs is what
# strict act-as demands of anyone whose invocation runs as the Dataform SA.
# ----------------------------------------------------------------------------
locals {
  invokers = merge(
    var.deployer_sa_email == null ? {} : { deployer = "serviceAccount:${var.deployer_sa_email}" },
    { for email in var.editor_emails : email => "user:${email}" },
  )
}

resource "google_dataform_repository_iam_member" "invoker" {
  provider = google-beta
  for_each = local.invokers

  project    = var.project_id
  region     = var.region
  repository = google_dataform_repository.this.name
  role       = "roles/dataform.editor"
  member     = each.value
}

resource "google_service_account_iam_member" "invoker_act_as" {
  for_each = local.invokers

  service_account_id = local.dataform_sa_id
  role               = "roles/iam.serviceAccountUser"
  member             = each.value
}
