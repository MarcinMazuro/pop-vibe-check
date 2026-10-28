# ----------------------------------------------------------------------------
# MLflow tracking server: Cloud Run service, Cloud SQL Postgres, behind IAP.
#
# Three stores, three owners:
#   - run metadata and the model registry live in Postgres (Cloud SQL),
#     reached over Cloud Run's built-in Cloud SQL connection (a unix socket
#     under /cloudsql, no authorized networks, no VPC connector);
#   - artifacts stay where training has always written them, under
#     nlp/mlruns/ on the artifacts bucket. The server runs with
#     --no-serve-artifacts, so clients write there with their own
#     credentials and the server only reads back for the UI (the grant
#     lives in modules/storage, next to the bucket);
#   - who may open the UI is IAP's decision, as for the dashboard.
#
# The instance runs permanently. It is the one standing cost this module
# adds (a shared-core db-f1-micro); the service itself scales to zero.
#
# IAP is switched on outside Terraform, as for the dashboard: provider 5.x
# has no iap_enabled field on google_cloud_run_v2_service. See README.md.
# ----------------------------------------------------------------------------
data "google_project" "this" {
  project_id = var.project_id
}

locals {
  name              = "${var.name_prefix}-mlflow-${var.env}"
  iap_service_agent = "service-${data.google_project.this.number}@gcp-sa-iap.iam.gserviceaccount.com"
}

# ----------------------------------------------------------------------------
# Cloud SQL.
#
# Enterprise edition is set explicitly: new Postgres 16 instances default to
# Enterprise Plus, which has no shared-core tiers. A public IP with no
# authorized networks admits only the Cloud SQL connectors, which
# authenticate with IAM (roles/cloudsql.client below) and encrypt.
# ----------------------------------------------------------------------------
resource "google_sql_database_instance" "mlflow" {
  project             = var.project_id
  name                = local.name
  region              = var.region
  database_version    = var.database_version
  deletion_protection = true

  settings {
    edition           = "ENTERPRISE"
    tier              = var.tier
    availability_type = "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = 10
    disk_autoresize   = true

    deletion_protection_enabled = true
    user_labels                 = var.labels

    ip_configuration {
      ipv4_enabled = true
    }

    # Run history is the point of the instance; a week of daily backups
    # costs cents at this size.
    backup_configuration {
      enabled    = true
      start_time = "02:00"

      backup_retention_settings {
        retained_backups = 7
      }
    }
  }
}

resource "google_sql_database" "mlflow" {
  project  = var.project_id
  instance = google_sql_database_instance.mlflow.name
  name     = "mlflow"
}

# ----------------------------------------------------------------------------
# Database password.
#
# Unlike the external credentials in modules/secrets, this one is born
# here: Terraform generates it, sets it on the SQL user and stores it in
# Secret Manager for the service. It is therefore in Terraform state, which
# the private, versioned state bucket already protects; the alternative,
# creating the user out of band, would leave it outside Terraform.
# Alphanumeric only, because it is spliced into a connection URI.
# ----------------------------------------------------------------------------
resource "random_password" "db" {
  length  = 32
  special = false
}

resource "google_sql_user" "mlflow" {
  project  = var.project_id
  instance = google_sql_database_instance.mlflow.name
  name     = "mlflow"
  password = random_password.db.result
}

resource "google_secret_manager_secret" "db_password" {
  project   = var.project_id
  secret_id = "${local.name}-db-password"

  replication {
    auto {}
  }

  labels = var.labels
}

resource "google_secret_manager_secret_version" "db_password" {
  secret      = google_secret_manager_secret.db_password.id
  secret_data = random_password.db.result
}

resource "google_secret_manager_secret_iam_member" "db_password_accessor" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.db_password.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.mlflow_sa_email}"
}

# Project-level: cloudsql.client has no instance-level IAM binding.
resource "google_project_iam_member" "mlflow_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${var.mlflow_sa_email}"
}

# ----------------------------------------------------------------------------
# The service.
#
# One instance, one worker: the load is a handful of people and a training
# run, and a single process keeps the first boot's schema creation free of
# races. The image builds the backend URI from the env below at start-up.
#
# MLflow's security middleware rejects any Host it does not know. The
# run.app host is only known after creation, so it is matched by pattern;
# both run.app URL forms start with the service name.
# ----------------------------------------------------------------------------
resource "google_cloud_run_v2_service" "mlflow" {
  project  = var.project_id
  location = var.region
  name     = local.name
  ingress  = "INGRESS_TRAFFIC_ALL"

  labels = var.labels

  template {
    service_account = var.mlflow_sa_email

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.mlflow.connection_name]
      }
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
        cpu_idle = true
      }

      env {
        name  = "CLOUD_SQL_CONNECTION_NAME"
        value = google_sql_database_instance.mlflow.connection_name
      }

      env {
        name  = "DB_NAME"
        value = google_sql_database.mlflow.name
      }

      env {
        name  = "DB_USER"
        value = google_sql_user.mlflow.name
      }

      env {
        name = "DB_PASSWORD"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.db_password.secret_id
            version = "latest"
          }
        }
      }

      env {
        name  = "ARTIFACT_ROOT"
        value = var.artifact_root
      }

      env {
        name  = "MLFLOW_SERVER_ALLOWED_HOSTS"
        value = "${local.name}-*.run.app"
      }

      env {
        name  = "MLFLOW_SERVER_CORS_ALLOWED_ORIGINS"
        value = "https://${local.name}-*.run.app"
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }
    }
  }

  lifecycle {
    # Image deployed by Cloud Build, as for the dashboard.
    ignore_changes = [
      launch_stage,
      client,
      client_version,
      template[0].containers[0].image,
    ]
  }

  # Cloud Run validates the secret reference when it creates a revision,
  # so the version and the accessor grant must exist first.
  depends_on = [
    google_secret_manager_secret_version.db_password,
    google_secret_manager_secret_iam_member.db_password_accessor,
    google_project_iam_member.mlflow_sql_client,
  ]
}

# ----------------------------------------------------------------------------
# Access through IAP.
#
# People: the project-level httpsResourceAccessor grant made for the
# dashboard's viewers (modules/dashboard) covers every IAP resource in the
# project, this one included. Provider 5.x has no per-service IAP IAM
# resource, so there is no narrower grant to make.
#
# Programs: client_sa_emails (the Workbench trainer) get the same role and
# present a Google-signed ID token, minted for the IAP OAuth client.
# ----------------------------------------------------------------------------
resource "google_cloud_run_v2_service_iam_member" "iap_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.mlflow.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${local.iap_service_agent}"
}

resource "google_project_iam_member" "client" {
  for_each = toset(var.client_sa_emails)

  project = var.project_id
  role    = "roles/iap.httpsResourceAccessor"
  member  = "serviceAccount:${each.value}"
}

# ----------------------------------------------------------------------------
# Image deployer (Cloud Build): run.developer on the service, actAs on its
# runtime SA — the same pair the dashboard grants.
# ----------------------------------------------------------------------------
resource "google_cloud_run_v2_service_iam_member" "deployer" {
  count = var.deployer_sa_email == null ? 0 : 1

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.mlflow.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${var.deployer_sa_email}"
}

resource "google_service_account_iam_member" "deployer_act_as" {
  count = var.deployer_sa_email == null ? 0 : 1

  service_account_id = "projects/${var.project_id}/serviceAccounts/${var.mlflow_sa_email}"
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.deployer_sa_email}"
}
