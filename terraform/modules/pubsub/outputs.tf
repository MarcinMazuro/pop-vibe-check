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

output "dataflow_subscription_name" {
  description = "Short name of the Dataflow subscription (e.g. 'co-events-dataflow-sub-dev')."
  value       = google_pubsub_subscription.dataflow.name
}

output "dataflow_subscription_id" {
  description = "Fully-qualified Dataflow subscription resource ID (projects/.../subscriptions/...). This is what the Beam pipeline's --subscription / input_subscription parameter wants."
  value       = google_pubsub_subscription.dataflow.id
}

output "dlq_topic_name" {
  description = "Short name of the dead-letter topic (e.g. 'co-events-dlq-topic-dev')."
  value       = google_pubsub_topic.dlq.name
}

output "dlq_topic_id" {
  description = "Fully-qualified dead-letter topic resource ID. The Beam pipeline publishes unparseable records here via its tagged dead-letter output."
  value       = google_pubsub_topic.dlq.id
}

output "dlq_subscription_name" {
  description = "Short name of the DLQ inspection subscription. Use in `gcloud pubsub subscriptions pull` to read dead-lettered records."
  value       = google_pubsub_subscription.dlq.name
}
