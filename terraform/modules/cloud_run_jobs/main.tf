# ----------------------------------------------------------------------------
# Reddit collector Cloud Run Job.
#
# Image defaults to the public 'pause' placeholder so the job can be
# provisioned and validated before the real collector image is built.
# Override `reddit_image_uri` to the Artifact Registry URI once the
# Python container exists.
#
# Runtime env vars split into two layers:
# - Deploy-time literals (TARGET_BUCKET) — set here, baked into the
#   template, identical across every execution.
# - Deploy-time secret references (REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET,
#   REDDIT_USER_AGENT, AUTHOR_HASH_SALT) — resolved by Cloud Run at
#   container start, never visible in Terraform state.
# - Execution-time params (EVENT_ID, WINDOW_FROM, WINDOW_TO) — NOT set
#   here. Operator supplies them per run via
#   `gcloud run jobs execute --update-env-vars=EVENT_ID=...,WINDOW_FROM=...,WINDOW_TO=...`.
# ----------------------------------------------------------------------------
resource "google_cloud_run_v2_job" "reddit_collector" {
  project  = var.project_id
  location = var.region
  name     = "${var.name_prefix}-reddit-collector-${var.env}"

  labels = var.labels

  template {
    template {
      service_account = var.reddit_collector_sa_email
      timeout         = var.task_timeout
      max_retries     = var.max_retries

      containers {
        image = var.reddit_image_uri

        resources {
          limits = {
            memory = var.memory
            cpu    = var.cpu
          }
        }

        env {
          name  = "TARGET_BUCKET"
          value = var.raw_archive_bucket_name
        }

        env {
          name = "REDDIT_CLIENT_ID"
          value_source {
            secret_key_ref {
              secret  = var.secret_names["reddit-client-id"]
              version = "latest"
            }
          }
        }

        env {
          name = "REDDIT_CLIENT_SECRET"
          value_source {
            secret_key_ref {
              secret  = var.secret_names["reddit-client-secret"]
              version = "latest"
            }
          }
        }

        env {
          name = "REDDIT_USER_AGENT"
          value_source {
            secret_key_ref {
              secret  = var.secret_names["reddit-user-agent"]
              version = "latest"
            }
          }
        }

        env {
          name = "AUTHOR_HASH_SALT"
          value_source {
            secret_key_ref {
              secret  = var.secret_names["author-hash-salt"]
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    # The pause image has no env vars to validate, so on the first apply
    # Cloud Run records the secret references as "latest" without
    # resolving them. Subsequent reapplies see no diff. Ignore launch
    # stage to avoid spurious diffs from Google's beta-channel rollouts.
    ignore_changes = [launch_stage]
  }
}

# ----------------------------------------------------------------------------
# YouTube collector Cloud Run Job.
#
# Same shape as the Reddit job. Different SA, different image, and the
# only credential secret is the YouTube API key (plus the shared
# author-hash salt for username hashing).
# ----------------------------------------------------------------------------
resource "google_cloud_run_v2_job" "youtube_collector" {
  project  = var.project_id
  location = var.region
  name     = "${var.name_prefix}-youtube-collector-${var.env}"

  labels = var.labels

  template {
    template {
      service_account = var.youtube_collector_sa_email
      timeout         = var.task_timeout
      max_retries     = var.max_retries

      containers {
        image = var.youtube_image_uri

        resources {
          limits = {
            memory = var.memory
            cpu    = var.cpu
          }
        }

        env {
          name  = "TARGET_BUCKET"
          value = var.raw_archive_bucket_name
        }

        env {
          name = "YOUTUBE_API_KEY"
          value_source {
            secret_key_ref {
              secret  = var.secret_names["youtube-api-key"]
              version = "latest"
            }
          }
        }

        env {
          name = "AUTHOR_HASH_SALT"
          value_source {
            secret_key_ref {
              secret  = var.secret_names["author-hash-salt"]
              version = "latest"
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [launch_stage]
  }
}

# ----------------------------------------------------------------------------
# Bucket-level write IAM for the collectors on the raw archive.
#
# The storage module did not grant these because the collector SAs did not
# exist when it was applied. Lives here, in the consumer module, so the
# binding cycle (collector → bucket) is co-located with the job that
# actually needs it. `objectAdmin` rather than `objectCreator` so the
# collectors can also list / delete their own output on cleanup.
# ----------------------------------------------------------------------------
resource "google_storage_bucket_iam_member" "reddit_raw_archive_writer" {
  bucket = var.raw_archive_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.reddit_collector_sa_email}"
}

resource "google_storage_bucket_iam_member" "youtube_raw_archive_writer" {
  bucket = var.raw_archive_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.youtube_collector_sa_email}"
}
