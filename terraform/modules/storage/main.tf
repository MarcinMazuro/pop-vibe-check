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
# Stores Cloud Build logs, generic build artifacts, and (under nlp/) the
# DistilBERT dataset cache and MLflow tracking files. Build-log prefixes
# are disposable and hard-deleted after 30 days; nlp/ is retained so a
# stopped Workbench instance can resume without re-downloading Hugging
# Face datasets.
# ----------------------------------------------------------------------------
resource "google_storage_bucket" "tf_artifacts" {
  name     = "${var.name_prefix}-tf-artifacts-${var.env}"
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = var.force_destroy_artifacts

  # Prefix-scoped on purpose: a bucket-wide 30-day delete would wipe
  # nlp/datasets/ and nlp/mlruns/ between training sessions. Only the
  # churn prefixes are swept; nlp/ (and anything else) survives.
  lifecycle_rule {
    condition {
      age            = 30
      matches_prefix = ["logs/", "cloudbuild/"]
    }
    action {
      type = "Delete"
    }
  }

  labels = var.labels
}

# ----------------------------------------------------------------------------
# Source tarballs for manual `gcloud builds submit`.
#
# A build that runs as a user-specified SA reads its uploaded source with
# that SA's own credentials. Manual submits stage the tarball under
# cloudbuild/source/ here (--gcs-source-staging-dir), which the 30-day
# lifecycle rule above already sweeps. Trigger builds fetch source from
# GitHub and never use this.
# ----------------------------------------------------------------------------
resource "google_storage_bucket_iam_member" "cloud_build_source_reader" {
  for_each = toset(var.cloud_build_source_reader_emails)

  bucket = google_storage_bucket.tf_artifacts.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${each.value}"

  condition {
    title       = "cloudbuild-source-only"
    description = "Manual build source tarballs under cloudbuild/source/ only."
    expression  = "resource.name.startsWith(\"projects/_/buckets/${google_storage_bucket.tf_artifacts.name}/objects/cloudbuild/source/\")"
  }
}

# ----------------------------------------------------------------------------
# ML trainer access to the artifacts bucket.
#
# objectAdmin (not just objectViewer) because Workbench writes the
# dataset cache, MLflow runs, and exported weights under nlp/. Scoped to
# this one bucket, co-located with it per the project's IAM convention.
# ----------------------------------------------------------------------------
resource "google_storage_bucket_iam_member" "ml_trainer_object_admin" {
  bucket = google_storage_bucket.tf_artifacts.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.ml_trainer_sa_email}"
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

# ----------------------------------------------------------------------------
# Cloud Build access to the Flex Template specs.
#
# The sentiment-pipeline trigger writes a versioned spec plus the "current"
# spec under templates/ on every merge to main, and the same SA reads it
# back when it launches a job. objectAdmin because refreshing the current
# spec overwrites an object (create + delete). The IAM condition keeps it
# off staging/ and temp/, which hold live job data.
# ----------------------------------------------------------------------------
resource "google_storage_bucket_iam_member" "cloud_build_templates" {
  count = var.cloud_build_sa_email == null ? 0 : 1

  bucket = google_storage_bucket.dataflow_temp.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.cloud_build_sa_email}"

  condition {
    title       = "templates-prefix-only"
    description = "Flex Template specs under templates/ only."
    expression  = "resource.name.startsWith(\"projects/_/buckets/${google_storage_bucket.dataflow_temp.name}/objects/templates/\")"
  }
}
