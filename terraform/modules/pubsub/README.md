# modules/pubsub

Provisions the Pub/Sub boundary between the replay publisher and the streaming pipeline: the events topic, the Dataflow subscription that feeds the Beam pipeline, a manual verification subscription, and a dead-letter topic with an inspection subscription.

## What this creates

- **`{name_prefix}-events-topic-{env}`** — the topic the publisher Cloud Run Job replays staged records into, under a single ordering key.
- **`{name_prefix}-events-dataflow-sub-{env}`** — the streaming pipeline's subscription. Message ordering on, 60s ack deadline, never-expiring, with a `dead_letter_policy` pointing at the DLQ topic (`max_delivery_attempts = 5`).
- **`{name_prefix}-events-verify-sub-{env}`** — ordered pull subscription for manual verification with `gcloud pubsub subscriptions pull --auto-ack`. Never expires (empty TTL) so it survives idle weeks between demos.
- **`{name_prefix}-events-dlq-topic-{env}`** + **`{name_prefix}-events-dlq-sub-{env}`** — dead-letter topic and a never-expiring pull subscription for manually inspecting dead records.
- IAM (all co-located with the owned resource, per project convention):
  - `roles/pubsub.publisher` on the events topic for the publisher SA.
  - `roles/pubsub.subscriber` on the Dataflow subscription and `roles/pubsub.publisher` on the DLQ topic for the Dataflow worker SA.
  - `roles/pubsub.publisher` on the DLQ topic and `roles/pubsub.subscriber` on the Dataflow subscription for the **Pub/Sub service agent** — required or dead-lettering fails silently (see "Dead-letter paths" below).

## Ordering: delivery vs processing

The events topic is published under one ordering key, and the Dataflow subscription sets `enable_message_ordering = true`. That guarantees ordered **delivery** into Dataflow — Pub/Sub hands the pipeline messages in publish order per key. It does **not** guarantee ordered **processing**: Beam spreads work across bundles and workers with no cross-bundle order. The pipeline re-establishes global chronology in the analytical output by **event-time windowing on `created_utc`**, not by the ordering key. The key keeps the stream tidy and the demo legible; the windowing is what actually satisfies the project's global-ordering requirement.

## Dead-letter paths

There are two ways a record can reach the DLQ topic, and only one carries traffic in practice:

1. **Subscription `dead_letter_policy` (backstop).** Fires only after Pub/Sub redelivers a message `max_delivery_attempts` (5) times and the consumer nacks each time. Beam's Pub/Sub source generally retries a failing *bundle* rather than nacking individual messages, so this path rarely triggers — it is a safety net for pathological redelivery. This is the path that needs the **Pub/Sub service agent** grants: when a subscription dead-letters, Pub/Sub (as `service-<project_number>@gcp-sa-pubsub.iam.gserviceaccount.com`) publishes to the DLQ topic and acks the source subscription, and it has no rights by default. The project number is resolved via a `google_project` data lookup, never hardcoded.
2. **Pipeline tagged output (load-bearing).** PR 3's Beam graph routes records it cannot parse or classify to a dead-letter PCollection and publishes them to the DLQ topic explicitly. This is how bad records actually get captured — hence the Dataflow worker SA's `pubsub.publisher` on the DLQ topic.

Both exist; only (2) is load-bearing.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | GCP project ID |
| `name_prefix` | string | yes | — | Short release prefix (2-8 chars, lowercase alphanumeric/hyphen) |
| `env` | string | yes | — | Environment name; suffixed into resource names |
| `labels` | map(string) | yes | — | Labels applied to topics and subscriptions |
| `publisher_sa_email` | string | yes | — | Publisher SA granted publish on the events topic |
| `dataflow_worker_sa_email` | string | yes | — | Dataflow worker SA granted subscribe on the Dataflow subscription and publish on the DLQ topic |

## Outputs

| Name | Description |
|---|---|
| `events_topic_name` | Short topic name, e.g. `co-events-topic-dev` |
| `events_topic_id` | Fully-qualified topic resource ID |
| `verify_subscription_name` | Short name of the verification subscription |
| `dataflow_subscription_name` | Short name of the Dataflow subscription |
| `dataflow_subscription_id` | Fully-qualified Dataflow subscription resource ID — the pipeline's `input_subscription` |
| `dlq_topic_name` | Short name of the dead-letter topic |
| `dlq_topic_id` | Fully-qualified dead-letter topic resource ID — the pipeline's tagged dead-letter output target |
| `dlq_subscription_name` | Short name of the DLQ inspection subscription |

## Notes

- **Ordering end-to-end.** `enable_message_ordering = true` on the Dataflow and verify subscriptions only holds if the publisher also publishes with an ordering key through the regional endpoint (`europe-central2-pubsub.googleapis.com`). But ordered delivery is not ordered processing — see "Ordering: delivery vs processing" above.
- **Phase 1 continuation.** The pipeline PR (PR 3) adds the Beam graph that consumes `{name_prefix}-events-dataflow-sub-{env}`, writes `events_landing`, and publishes unparseable records to `{name_prefix}-events-dlq-topic-{env}`. The subscription, topic, and IAM it needs are all in place now.
