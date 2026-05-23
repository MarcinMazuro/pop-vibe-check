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
  force_destroy               = false

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
# Stores build logs and Dataflow Flex Template payloads. Disposable by
# design — hard-deletes everything older than 30 days so the bucket cannot
# grow unbounded between defenses.
# ----------------------------------------------------------------------------
resource "google_storage_bucket" "tf_artifacts" {
  name     = "${var.name_prefix}-tf-artifacts-${var.env}"
  location = var.region

  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

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
