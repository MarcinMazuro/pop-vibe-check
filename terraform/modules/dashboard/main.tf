# ----------------------------------------------------------------------------
# Streamlit dashboard Cloud Run service, behind Identity-Aware Proxy.
#
# The service reads the reporting dataset's authorized views as its own
# runtime SA, not as the viewer: IAP decides who may open the page, the
# SA's grants decide what the page may read. Viewers therefore need no
# BigQuery access of their own to use the dashboard.
#
# IAP itself is switched on outside Terraform. Provider 5.x has no
# iap_enabled field on google_cloud_run_v2_service, so it is set once with
# `gcloud run services update --iap` (see README.md). The image deploys
# (`gcloud run services update --image`) keep it; a Terraform change to
# this service may switch it off again. That fails closed: without IAP the
# run.app URL wants run.invoker, which no viewer holds, so everyone gets a
# 403 until `--iap` is re-run.
#
# Image defaults to Google's public 'hello' sample: unlike a job, a
# service must answer on $PORT to be created, which the 'pause' image the
# jobs start on does not. Cloud Build deploys the real image on every
# merge to main and the image field is ignored afterwards.
# ----------------------------------------------------------------------------
data "google_project" "this" {
  project_id = var.project_id
}

locals {
  iap_service_agent = "service-${data.google_project.this.number}@gcp-sa-iap.iam.gserviceaccount.com"
}

resource "google_cloud_run_v2_service" "dashboard" {
  project  = var.project_id
  location = var.region
  name     = "${var.name_prefix}-dashboard-${var.env}"
  ingress  = "INGRESS_TRAFFIC_ALL"

  labels = var.labels

  template {
    service_account = var.dashboard_sa_email

    # A Streamlit session is one long-lived websocket. The timeout caps
    # how long it lives before the browser reconnects; affinity sends the
    # reconnect back to the instance holding the session state.
    timeout          = var.request_timeout
    session_affinity = true

    scaling {
      min_instance_count = 0
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image_uri

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          memory = var.memory
          cpu    = var.cpu
        }
        # Billed only while a request (a websocket) is open.
        cpu_idle = true
      }

      env {
        name  = "PROJECT_ID"
        value = var.project_id
      }

      env {
        name  = "REPORTING_DATASET"
        value = var.reporting_dataset_id
      }
    }
  }

  lifecycle {
    # Image deployed by Cloud Build, as for the jobs in cloud_run_jobs.
    ignore_changes = [
      launch_stage,
      client,
      client_version,
      template[0].containers[0].image,
    ]
  }
}

# ----------------------------------------------------------------------------
# Access through IAP.
#
# IAP forwards an authenticated viewer's request as its own service agent,
# so the agent is the only principal that invokes the service directly.
# The agent exists once iap.googleapis.com is enabled and its identity
# created (`gcloud beta services identity create --service=iap.googleapis.com`).
#
# Viewers get httpsResourceAccessor on the project: provider 5.x has no
# per-service IAP IAM resource, and the project-level grant is inherited by
# every IAP-protected resource in it — this service is the only one.
# ----------------------------------------------------------------------------
resource "google_cloud_run_v2_service_iam_member" "iap_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.dashboard.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.iap_service_agent}"
}

resource "google_project_iam_member" "viewer" {
  for_each = toset(var.viewer_emails)

  project = var.project_id
  role    = "roles/iap.httpsResourceAccessor"
  member  = "user:${each.value}"
}

# ----------------------------------------------------------------------------
# What the dashboard may read: the reporting dataset only, as the human
# report viewers do (see modules/bigquery). The authorized views carry the
# read on the analytics dataset themselves.
# ----------------------------------------------------------------------------
resource "google_bigquery_dataset_access" "dashboard_data_viewer" {
  project       = var.project_id
  dataset_id    = var.reporting_dataset_id
  role          = "roles/bigquery.dataViewer"
  user_by_email = var.dashboard_sa_email
}

resource "google_project_iam_member" "dashboard_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${var.dashboard_sa_email}"
}

# ----------------------------------------------------------------------------
# Image deployer (Cloud Build): run.developer on the service, actAs on its
# runtime SA — the same pair cloud_run_jobs grants for the jobs.
# ----------------------------------------------------------------------------
resource "google_cloud_run_v2_service_iam_member" "deployer" {
  count = var.deployer_sa_email == null ? 0 : 1

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.dashboard.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${var.deployer_sa_email}"
}

resource "google_service_account_iam_member" "deployer_act_as" {
  count = var.deployer_sa_email == null ? 0 : 1

  service_account_id = "projects/${var.project_id}/serviceAccounts/${var.dashboard_sa_email}"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.deployer_sa_email}"
}
