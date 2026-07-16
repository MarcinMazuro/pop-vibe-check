output "events_topic_name" {
  description = "Short topic name (e.g. 'co-events-topic-dev'). Use in the publisher's PUBSUB_TOPIC env var."
  value       = google_pubsub_topic.events.name
}

output "events_topic_id" {
  description = "Fully-qualified topic resource ID (projects/.../topics/...). Use when an IAM binding or subscription wants the resource ID."
  value       = google_pubsub_topic.events.id
}

output "verify_subscription_name" {
  description = "Short name of the manual verification subscription. Use in `gcloud pubsub subscriptions pull`."
  value       = google_pubsub_subscription.verify.name
}
