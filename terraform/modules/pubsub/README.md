# modules/pubsub

Provisions the Pub/Sub boundary between the replay publisher and the streaming pipeline: the events topic plus a manual verification subscription. The Dataflow subscription and a dead-letter topic land in a later Phase 1 PR — a DLQ is meaningless until a real consumer can nack messages.

## What this creates

- **`{name_prefix}-events-topic-{env}`** — the topic the publisher Cloud Run Job replays staged records into, in global chronological order under a single ordering key.
- **`{name_prefix}-events-verify-sub-{env}`** — ordered pull subscription for manual verification with `gcloud pubsub subscriptions pull --auto-ack`. Never expires (empty TTL) so it survives idle weeks between demos.
- Topic-level `roles/pubsub.publisher` for the publisher SA (binding co-located with the owned resource, per project convention).

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | GCP project ID |
| `name_prefix` | string | yes | — | Short release prefix (2-8 chars, lowercase alphanumeric/hyphen) |
| `env` | string | yes | — | Environment name; suffixed into resource names |
| `labels` | map(string) | yes | — | Labels applied to topic and subscription |
| `publisher_sa_email` | string | yes | — | Publisher SA granted publish on the topic |

## Outputs

| Name | Description |
|---|---|
| `events_topic_name` | Short topic name, e.g. `co-events-topic-dev` |
| `events_topic_id` | Fully-qualified topic resource ID |
| `verify_subscription_name` | Short name of the verification subscription |

## Notes

- **Ordering.** The subscription sets `enable_message_ordering = true`; the publisher must also publish with an ordering key through the regional endpoint (`europe-central2-pubsub.googleapis.com`) for the guarantee to hold end-to-end.
- **Phase 1 continuation.** The Dataflow PR adds: a `{name_prefix}-events-dlq-{env}` dead-letter topic, a Dataflow pull subscription with `dead_letter_policy`, and subscriber IAM for the Dataflow worker SA.
