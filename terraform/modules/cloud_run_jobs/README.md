# modules/cloud_run_jobs

Provisions the Reddit and YouTube collector Cloud Run Jobs and the replay publisher job, plus the bucket-level IAM bindings they need on the raw archive.

## What this creates

- **`{name_prefix}-reddit-collector-{env}`** — Cloud Run v2 Job running as the Reddit collector SA. Default image is the public `pause` placeholder; override `reddit_image_uri` to the Artifact Registry URI once the real container is built. Memory 2Gi, CPU 1, timeout 1h, max 3 retries (all configurable).
- **`{name_prefix}-youtube-collector-{env}`** — same shape, runs as the YouTube collector SA.
- **`{name_prefix}-publisher-{env}`** — the replay publisher: loads the raw archive into BigQuery staging and replays it to Pub/Sub in chronological order with time compression. Timeout 6h, `max_retries = 0` (an automatic retry of a partial replay would double-publish).
- **`roles/storage.objectAdmin`** for each collector SA and **`roles/storage.objectViewer`** for the publisher SA on the raw archive bucket. These bindings live here, not in `storage/`, because the SAs the bindings reference didn't exist when `storage/` was applied — the convention is "bindings next to whichever module knows about both sides".

## Runtime environment

Each job has three layers of env-var configuration:

| Layer | Where set | Examples |
|---|---|---|
| Deploy-time literal | This module's `env { name = ... value = ... }` blocks | `TARGET_BUCKET`; publisher: `PROJECT_ID`, `BQ_DATASET`, `BQ_LANDING_TABLE`, `BQ_STAGING_TABLE`, `RAW_ARCHIVE_BUCKET`, `PUBSUB_TOPIC`, `SPEEDUP`, `MAX_SLEEP_SECONDS` |
| Deploy-time secret reference | `secret_key_ref` blocks; resolved by Cloud Run at container start, never in TF state | `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`, `YOUTUBE_API_KEY`, `AUTHOR_HASH_SALT` |
| Execution-time per-run | `--update-env-vars` on `gcloud run jobs execute` | `EVENT_ID`, `WINDOW_FROM`, `WINDOW_TO`; publisher: `RUN_LOAD` plus `SPEEDUP` / `MAX_SLEEP_SECONDS` overrides |

Execution-time params are intentionally not in the template — they change every run (event window, time range) and are the operator's per-execution input.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | GCP project ID |
| `name_prefix` | string | yes | — | Short release prefix (2-8 chars) |
| `env` | string | yes | — | Environment name; suffixed into job names |
| `region` | string | yes | — | Region the jobs run in |
| `labels` | map(string) | yes | — | Labels applied to every job |
| `raw_archive_bucket_name` | string | yes | — | Wired into `TARGET_BUCKET` env var |
| `reddit_collector_sa_email` | string | yes | — | Runtime identity for the Reddit job |
| `youtube_collector_sa_email` | string | yes | — | Runtime identity for the YouTube job |
| `secret_names` | map(string) | yes | — | Output of the `secrets` module; binds creds + salt as env vars |
| `publisher_sa_email` | string | yes | — | Runtime identity for the publisher job; granted read on the raw archive |
| `bq_dataset_id` | string | yes | — | Wired into the publisher's `BQ_DATASET` |
| `bq_landing_table_id` | string | yes | — | Wired into `BQ_LANDING_TABLE` |
| `bq_staging_table_id` | string | yes | — | Wired into `BQ_STAGING_TABLE` |
| `events_topic_name` | string | yes | — | Wired into `PUBSUB_TOPIC` |
| `reddit_image_uri` | string | no | `gcr.io/google-containers/pause` | Full image URI for the Reddit container |
| `youtube_image_uri` | string | no | `gcr.io/google-containers/pause` | Full image URI for the YouTube container |
| `publisher_image_uri` | string | no | `gcr.io/google-containers/pause` | Full image URI for the publisher container |
| `memory` | string | no | `2Gi` | Per-task memory limit |
| `cpu` | string | no | `1` | Per-task CPU limit |
| `task_timeout` | string | no | `3600s` | Hard timeout per collector task execution |
| `publisher_task_timeout` | string | no | `21600s` | Hard timeout per publisher replay execution |
| `max_retries` | number | no | `3` | Automatic retries per collector task on failure (publisher is fixed at 0) |

## Outputs

| Name | Description |
|---|---|
| `reddit_job_name` | Short job name; use in `gcloud run jobs execute` |
| `youtube_job_name` | Short job name; use in `gcloud run jobs execute` |
| `reddit_job_id` | Fully-qualified job resource ID |
| `youtube_job_id` | Fully-qualified job resource ID |
| `publisher_job_name` | Short job name of the replay publisher |
| `publisher_job_id` | Fully-qualified job resource ID for the publisher |

## Triggering an execution

The job exists in deployed state but does nothing until an operator triggers an execution:

```bash
gcloud run jobs execute co-reddit-collector-dev \
  --region=europe-central2 \
  --update-env-vars="EVENT_ID=launch,WINDOW_FROM=2025-04-24T00:00:00Z,WINDOW_TO=2025-04-26T00:00:00Z" \
  --wait
```

`--wait` blocks until the task finishes. Drop it to fire-and-forget; track in the Cloud Run UI.

## Notes

- **Default `pause` image is intentional.** Lets the module ship and validate end-to-end (job deploys, SA attaches, secrets bind, IAM works) before the Python collector image exists. Triggering execution with the pause image creates a task that sleeps until the timeout — useful for checking logs and SA attribution, useless for collecting data.
- **No VPC config.** Default Cloud Run egress already reaches `*.googleapis.com` (Secret Manager, GCS, Reddit/YouTube public APIs). Direct VPC egress requires `roles/compute.networkUser` on the subnet for the Cloud Run service identity — extra complexity not needed for Phase 0.
- **Bucket IAM here, not in storage/.** Because the storage module knows nothing about workload SAs and the iam module knows nothing about which buckets exist, the binding lives where both sides are visible — here.
- **No ingress.** Cloud Run Jobs are not HTTP services; they expose nothing externally and are only invoked via the Cloud Run API.
