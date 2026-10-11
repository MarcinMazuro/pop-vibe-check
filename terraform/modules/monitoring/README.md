# modules/monitoring

Alert policies for the streaming path: Dataflow job health, the cost of a
job left running, replay backlog, and dead-lettered records.

## What this creates

| Policy | Fires when | Why it matters |
|---|---|---|
| `… — Dataflow job failed` | `dataflow.googleapis.com/job/is_failed > 0` | The replay stopped mid-run. `events_landing` holds a partial run — do not promote it. |
| `… — Dataflow job running too long` | `job/elapsed_time > max_job_runtime_hours` | Cost guard. A streaming job bills continuously until drained; every replay here is minutes to hours. |
| `… — replay backlog ageing` | `oldest_unacked_message_age > backlog_age_alert_seconds` on the Dataflow subscription, for 5 minutes | Either nothing is consuming the replay, or the job is stuck. A paced replay always has *some* backlog, so the alert is on its **age**, not its size. |
| `… — dead-letter records` | `num_undelivered_messages > 0` on the DLQ subscription, for 5 minutes | Every dead-lettered record is a record missing from `events`. |

Each policy auto-closes after 7 days, because the gauges stop being
written once a job is drained and an open incident would otherwise never
resolve.

## Notification channels

This module does **not** create channels. The `budgets` module already
creates one email channel per recipient; pass its
`notification_channel_ids` output here so alerts and budget notifications
reach the same addresses. Creating a second channel for the same address
would mean a second verification email and duplicate alerts.

A recipient only receives mail after clicking GCP's verification link.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | Project the policies live in |
| `name_prefix` | string | yes | — | Release prefix in display names |
| `env` | string | yes | — | Environment in display names |
| `region` | string | yes | — | Dataflow region; used in the drain command in the alert documentation |
| `notification_channel_ids` | list(string) | yes | — | Channels every policy notifies |
| `dataflow_subscription_name` | string | yes | — | Short subscription name for the backlog policy |
| `dlq_subscription_name` | string | yes | — | Short subscription name for the dead-letter policy |
| `max_job_runtime_hours` | number | no | `6` | Runtime before the cost alert fires |
| `backlog_age_alert_seconds` | number | no | `1800` | Backlog age before the backlog alert fires |

## Outputs

| Name | Description |
|---|---|
| `alert_policy_names` | Resource names of the four policies |

## Notes

- **No uptime checks.** Nothing in this project serves HTTP.
- **Thresholds are per environment.** `dev` runs ad-hoc replays; a future
  `prod` would want a tighter `max_job_runtime_hours`.
- **Testing a policy** without breaking anything: publish a message to the
  DLQ topic (`gcloud pubsub topics publish <dlq-topic> --message=test`) and
  wait five minutes; the dead-letter policy should open an incident.
