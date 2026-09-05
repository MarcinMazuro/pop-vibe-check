# ----------------------------------------------------------------------------
# Events topic — the boundary between the replay publisher and the
# streaming pipeline.
#
# The publisher Cloud Run Job replays staged records here under a single
# ordering key, simulating a live stream. The Dataflow subscription below
# feeds the Beam pipeline.
#
# On ordering: the ordering key guarantees ordered *delivery* into
# Dataflow — Pub/Sub hands the pipeline messages per key in publish
# order. It does NOT guarantee ordered *processing*: Beam distributes work
# across bundles and workers with no cross-bundle order. Global chronology
# in the analytical output is re-established downstream by event-time
# windowing on `created_utc`, not by this ordering key. The key keeps the
# stream tidy and demo-legible; the windowing is what actually enforces
# the §6 "global chronological ordering" requirement.
# ----------------------------------------------------------------------------
resource "google_pubsub_topic" "events" {
  project = var.project_id
  name    = "${var.name_prefix}-events-topic-${var.env}"

  labels = var.labels
}

# ----------------------------------------------------------------------------
# Verification subscription.
#
# Exists so an operator can check replay output by hand:
#
#   gcloud pubsub subscriptions pull co-events-verify-sub-dev --auto-ack ...
#
# Message ordering is enabled so the pull preserves the publisher's
# chronological order (the publisher uses one constant ordering key).
# The empty expiration TTL keeps the subscription alive even though dev
# sits idle for weeks between demos — Pub/Sub would otherwise delete it
# after 31 days without activity. Dataflow gets its own subscription in
# a later PR; this one is for humans.
# ----------------------------------------------------------------------------
resource "google_pubsub_subscription" "verify" {
  project = var.project_id
  name    = "${var.name_prefix}-events-verify-sub-${var.env}"
  topic   = google_pubsub_topic.events.id

  enable_message_ordering = true
  ack_deadline_seconds    = 30

  expiration_policy {
    ttl = ""
  }

  labels = var.labels
}

# ----------------------------------------------------------------------------
# Topic-level publish IAM for the replay publisher.
#
# Resource-level binding co-located with the resource it grants access
# to, per project convention. The publisher SA itself is created in the
# iam module as a bare identity.
# ----------------------------------------------------------------------------
resource "google_pubsub_topic_iam_member" "publisher_sa_publish" {
  project = var.project_id
  topic   = google_pubsub_topic.events.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${var.publisher_sa_email}"
}

# ----------------------------------------------------------------------------
# Dead-letter topic + inspection subscription.
#
# Two distinct paths can land a record here, and it is worth being precise
# about which one actually carries traffic:
#
#   1. The subscription-level dead_letter_policy below is a backstop: it
#      fires only after Pub/Sub redelivers a message max_delivery_attempts
#      times and the consumer nacks each time. Beam's Pub/Sub source
#      generally *retries a failing bundle* rather than nacking individual
#      messages, so in practice this path rarely triggers — it is the
#      safety net for pathological redelivery, not the main road.
#   2. The load-bearing path is the pipeline's own tagged output: PR 3's
#      Beam graph routes records it cannot parse or classify to a dead-
#      letter PCollection and publishes them here explicitly. That is how
#      bad records will actually be captured for inspection.
#
# Both exist; only (2) is load-bearing. The dlq subscription is a manual
# pull target (never-expiring, same rationale as the verify subscription)
# so an operator can inspect whatever arrives by either path.
# ----------------------------------------------------------------------------
resource "google_pubsub_topic" "dlq" {
  project = var.project_id
  name    = "${var.name_prefix}-events-dlq-topic-${var.env}"

  labels = var.labels
}

resource "google_pubsub_subscription" "dlq" {
  project = var.project_id
  name    = "${var.name_prefix}-events-dlq-sub-${var.env}"
  topic   = google_pubsub_topic.dlq.id

  # Never expire: dev sits idle for weeks between demos, and a dead record
  # captured today must still be inspectable after the next defense.
  expiration_policy {
    ttl = ""
  }

  labels = var.labels
}

# ----------------------------------------------------------------------------
# Dataflow subscription — the streaming pipeline's feed off the events
# topic.
#
# enable_message_ordering matches the topic's ordering-key publishing (see
# the ordering note on the topic above). Never-expiring so it survives
# idle weeks. A 60s ack deadline gives the pipeline headroom to process a
# bundle before Pub/Sub considers a message unacked; Dataflow also extends
# deadlines automatically for in-flight work.
#
# dead_letter_policy points at the DLQ topic with max_delivery_attempts =
# 5 (path (1) above). This is the piece that needs the Pub/Sub service
# agent granted publish on the DLQ topic and subscribe on this
# subscription, granted below — without those, dead-lettering silently
# does nothing.
# ----------------------------------------------------------------------------
resource "google_pubsub_subscription" "dataflow" {
  project = var.project_id
  name    = "${var.name_prefix}-events-dataflow-sub-${var.env}"
  topic   = google_pubsub_topic.events.id

  enable_message_ordering = true
  ack_deadline_seconds    = 60

  expiration_policy {
    ttl = ""
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dlq.id
    max_delivery_attempts = 5
  }

  labels = var.labels
}

# ----------------------------------------------------------------------------
# Pub/Sub service agent grants for the dead-letter path.
#
# When a subscription dead-letters a message, Pub/Sub itself (acting as
# the per-project service agent) publishes it to the DLQ topic and acks it
# on the source subscription. Those two actions run as
# service-<project_number>@gcp-sa-pubsub.iam.gserviceaccount.com, which
# has no rights on our resources by default — so dead-lettering fails
# silently unless we grant them here. The project number comes from a
# data lookup, never hardcoded.
# ----------------------------------------------------------------------------
data "google_project" "this" {
  project_id = var.project_id
}

locals {
  pubsub_service_agent = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

resource "google_pubsub_topic_iam_member" "service_agent_dlq_publish" {
  project = var.project_id
  topic   = google_pubsub_topic.dlq.name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_service_agent
}

resource "google_pubsub_subscription_iam_member" "service_agent_source_subscribe" {
  project      = var.project_id
  subscription = google_pubsub_subscription.dataflow.name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_service_agent
}

# ----------------------------------------------------------------------------
# Dataflow worker access.
#
# subscriber on the Dataflow subscription lets the pipeline pull the
# stream; publisher on the DLQ topic lets it route unparseable records
# there explicitly (path (2) above — the load-bearing dead-letter path).
# Both bindings sit next to the resources they grant on, per convention.
#
# viewer is the third, non-obvious one. roles/pubsub.subscriber grants
# subscriptions.consume but NOT subscriptions.get, and Dataflow reads the
# subscription's configuration before it starts consuming. Without it the
# job runs, logs only a warning that sounds like a performance note
# ("Querying the configuration of Pub/Sub subscription ... failed"), and
# then quietly consumes nothing — the backlog sits unchanged while the
# job reports healthy. That failure mode cost a full debugging cycle on
# the first live run; the grant below is what fixed it.
# ----------------------------------------------------------------------------
resource "google_pubsub_subscription_iam_member" "dataflow_worker_subscribe" {
  project      = var.project_id
  subscription = google_pubsub_subscription.dataflow.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${var.dataflow_worker_sa_email}"
}

resource "google_pubsub_subscription_iam_member" "dataflow_worker_view" {
  project      = var.project_id
  subscription = google_pubsub_subscription.dataflow.name
  role         = "roles/pubsub.viewer"
  member       = "serviceAccount:${var.dataflow_worker_sa_email}"
}

resource "google_pubsub_topic_iam_member" "dataflow_worker_dlq_publish" {
  project = var.project_id
  topic   = google_pubsub_topic.dlq.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${var.dataflow_worker_sa_email}"
}

# ----------------------------------------------------------------------------
# Watermark tracking — the permission Dataflow needs that no predefined
# role grants narrowly enough.
#
# The pipeline reads Pub/Sub with a custom event-time attribute
# (created_utc), because the replay compresses months into minutes and
# publish time is therefore meaningless as a clock. To derive a watermark
# from that attribute, Dataflow creates its own tracking subscription on
# the source topic, named "<subscription>__df_internal<hash>", and deletes
# it when the job drains.
#
# Creating it needs pubsub.subscriptions.create plus
# pubsub.topics.attachSubscription. roles/pubsub.subscriber has neither.
# The documented answer is roles/pubsub.editor at project scope, which
# also grants publish and delete on every topic and subscription in the
# project — far more than this needs. The custom role below is the same
# capability with nothing extra.
#
# Without it the job runs, reports healthy, and consumes nothing: the only
# symptom is a repeating warning that "Creating watermark tracking pubsub
# subscription ... failed", while the backlog sits unchanged.
# ----------------------------------------------------------------------------
resource "google_project_iam_custom_role" "dataflow_watermark_tracking" {
  project     = var.project_id
  role_id     = "dataflowWatermarkTracking_${var.env}"
  title       = "Dataflow watermark tracking (${var.env})"
  description = "Lets the Dataflow worker SA manage the internal tracking subscription it needs to derive a watermark from a custom Pub/Sub timestamp attribute."

  permissions = [
    "pubsub.subscriptions.create",
    "pubsub.subscriptions.delete",
    "pubsub.subscriptions.get",
    "pubsub.subscriptions.update",
    "pubsub.topics.attachSubscription",
  ]
}

resource "google_project_iam_member" "dataflow_worker_watermark_tracking" {
  project = var.project_id
  role    = google_project_iam_custom_role.dataflow_watermark_tracking.id
  member  = "serviceAccount:${var.dataflow_worker_sa_email}"
}
