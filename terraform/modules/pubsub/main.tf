# ----------------------------------------------------------------------------
# Events topic — the boundary between the replay publisher and the
# streaming pipeline.
#
# The publisher Cloud Run Job replays staged records here in global
# chronological order using a single ordering key, simulating a live
# stream. Dataflow consumes the topic in the next Phase 1 step.
#
# A dead-letter topic is deliberately deferred to the Dataflow PR: a DLQ
# only matters once a real consumer can nack messages, and the Dataflow
# subscription (created there) is the first such consumer. The verify
# subscription below is pulled manually with --auto-ack, so it can never
# dead-letter anything.
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
