# ----------------------------------------------------------------------------
# Secret containers for collector credentials and the author-hash salt.
#
# Terraform owns the *containers* (google_secret_manager_secret). It does
# NOT own the *versions* (the actual secret values) — those are populated
# manually with `gcloud secrets versions add` exactly once per env, per
# the project's secrets convention. Putting plaintext values through tfvars
# or environment variables would leak them into state and CI logs.
#
# The author-hash-salt is special: rotating it invalidates author
# continuity across the historical dataset, so it is created once and
# never re-versioned unless a security incident forces it.
# ----------------------------------------------------------------------------
locals {
  secret_short_names = toset([
    "reddit-client-id",
    "reddit-client-secret",
    "reddit-user-agent",
    "youtube-api-key",
    "author-hash-salt",
  ])

  # Explicit per-secret accessor grants. Flat layout (one entry per
  # secret × SA pair) keeps the for_each key intuitive and avoids
  # nested-loop magic. When adding a secret above, add its grants here.
  accessor_grants = {
    "reddit-client-id/reddit-collector" = {
      secret_name = "reddit-client-id"
      sa_email    = var.collector_reddit_sa_email
    }
    "reddit-client-secret/reddit-collector" = {
      secret_name = "reddit-client-secret"
      sa_email    = var.collector_reddit_sa_email
    }
    "reddit-user-agent/reddit-collector" = {
      secret_name = "reddit-user-agent"
      sa_email    = var.collector_reddit_sa_email
    }
    "youtube-api-key/youtube-collector" = {
      secret_name = "youtube-api-key"
      sa_email    = var.collector_youtube_sa_email
    }
    "author-hash-salt/reddit-collector" = {
      secret_name = "author-hash-salt"
      sa_email    = var.collector_reddit_sa_email
    }
    "author-hash-salt/youtube-collector" = {
      secret_name = "author-hash-salt"
      sa_email    = var.collector_youtube_sa_email
    }
  }
}

resource "google_secret_manager_secret" "container" {
  for_each = local.secret_short_names

  project   = var.project_id
  secret_id = "${var.name_prefix}-${each.value}-${var.env}"

  # Multi-region Google-managed encryption. CMEK upgrade is a possible
  # later ADR but out of scope for the thesis.
  replication {
    auto {}
  }

  labels = var.labels
}

resource "google_secret_manager_secret_iam_member" "accessor" {
  for_each = local.accessor_grants

  project   = var.project_id
  secret_id = google_secret_manager_secret.container[each.value.secret_name].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${each.value.sa_email}"
}
