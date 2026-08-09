# ----------------------------------------------------------------------------
# Raw archive bucket.
#
# Append-only by convention: collectors write to new object paths, never
# overwrite. Versioning is off because there is nothing to version when the
# rule of the layer is "no overwrites" — enabling it would balloon storage
# cost for no recovery benefit. Public access prevention is enforced and
# uniform bucket-level access is on so the only way to grant access is via
# IAM bindings managed in code.
# ----------------------------------------------------------------------------
resource "google_storage_bucket" "raw_archive" {
  name     = "${var.name_prefix}-raw-archive-${var.env}"
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy_raw_archive

  versioning {
    enabled = false
  }

  # Standard → Coldline at 30 days. Raw archive is rarely re-read after the
  # initial replay simulation; Coldline keeps durability guarantees at ~25%
  # of the Standard storage cost.
  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type          = "SetStorageClass"
      storage_class = "COLDLINE"
    }
  }

  # Optional hard-delete. Disabled by default; enable per-env by setting
  # raw_archive_autodelete_days > 0 (useful for dev tear-downs, never in
  # prod where the archive is the only re-runnable source of truth).
  dynamic "lifecycle_rule" {
    for_each = var.raw_archive_autodelete_days > 0 ? [1] : []

    content {
      condition {
        age = var.raw_archive_autodelete_days
      }
      action {
        type = "Delete"
      }
    }
  }

  labels = var.labels
}

# ----------------------------------------------------------------------------
# Cloud Build / Terraform artifacts bucket.
#
# Stores Cloud Build logs and generic build artifacts. Disposable by
# design — hard-deletes everything older than 30 days so the bucket cannot
# grow unbounded between defenses. (Dataflow's runtime staging/temp and
# the Flex Template spec live in the dedicated dataflow-temp bucket below,
# not here — those have different retention needs.)
# ----------------------------------------------------------------------------
resource "google_storage_bucket" "tf_artifacts" {
  name     = "${var.name_prefix}-tf-artifacts-${var.env}"
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy_artifacts

  lifecycle_rule {
    condition {
      age = 30
    }
    action {
      type = "Delete"
    }
  }

  labels = var.labels
}

# ----------------------------------------------------------------------------
# Dataflow staging / temp bucket.
#
# Three prefixes with two very different retention needs, which is why the
# lifecycle rule is prefix-scoped rather than bucket-wide:
#   - staging/  — the pipeline's staged code/deps at launch
#   - temp/     — Beam's scratch during a run (BigQuery load temp files, etc.)
#   - templates/ — the Flex Template spec JSON the job is launched from
#
# staging/ and temp/ are churn: safe to hard-delete a week out so the
# bucket doesn't grow without bound. templates/ is NOT churn — it holds
# the spec every launch reads, so a bucket-wide 7-day delete would make
# the job unlaunchable a week after the template was built. The rule below
# therefore matches only the staging/ and temp/ prefixes; templates/
# survives indefinitely.
# ----------------------------------------------------------------------------
resource "google_storage_bucket" "dataflow_temp" {
  name     = "${var.name_prefix}-dataflow-temp-${var.env}"
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy_dataflow_temp

  lifecycle_rule {
    condition {
      age            = 7
      matches_prefix = ["staging/", "temp/"]
    }
    action {
      type = "Delete"
    }
  }

  labels = var.labels
}

# ----------------------------------------------------------------------------
# Dataflow worker access to the staging/temp bucket.
#
# objectAdmin (not just objectViewer) because the workers write staging
# and temp objects, not only read them. Scoped to this one bucket, and
# co-located with it per the project's resource-level IAM convention.
# ----------------------------------------------------------------------------
resource "google_storage_bucket_iam_member" "dataflow_worker_object_admin" {
  bucket = google_storage_bucket.dataflow_temp.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.dataflow_worker_sa_email}"
}
