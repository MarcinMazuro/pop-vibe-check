# publisher

Replay publisher for the data-source simulation: loads the GCS raw archive into BigQuery staging and replays it to Pub/Sub in global chronological order with time compression, as if the records were arriving live.

## How the simulation works

1. **Load (optional per run).** A native BigQuery load job truncate-loads every `*.jsonl.gz` object from the raw archive into `raw_landing`, then a `MERGE` deduplicates by `id` (freshest `collected_at` wins) into `raw_staging`. Re-running against unchanged data is a no-op.
2. **Replay.** The staging table is read with `ORDER BY created_utc, id`. For each record the publisher sleeps `min(real_gap / SPEEDUP, MAX_SLEEP_SECONDS)` and then publishes the record JSON to the events topic under the constant ordering key `global`. Bursts around lifecycle events keep their real shape; the months of dead air between events collapse to the clamp.

Wall time is bounded by `records × MAX_SLEEP_SECONDS`, independent of how long the simulated span is — ~4.2k records × 5 s is under 6 h absolute worst case, 10–25 minutes in practice at the default `SPEEDUP=86400` (one simulated day per wall second).

## Message shape

- **data** — the staged record JSON, exactly the 11 fields the collectors wrote (timestamps in ISO 8601 `Z` format).
- **attributes** — `source`, `event_tag`, `created_utc` (original), `replayed_at` (wall clock): filter and audit without parsing the body.
- **ordering key** — `global`; the client publishes through the regional endpoint (`europe-central2-pubsub.googleapis.com`), which Pub/Sub ordering requires.

## Configuration (environment variables)

| Variable | Layer | Default | Meaning |
|---|---|---|---|
| `PROJECT_ID` | deploy-time | — | GCP project |
| `BQ_DATASET` | deploy-time | — | Short dataset id (`co_analytics_dev`) |
| `BQ_LANDING_TABLE` | deploy-time | — | Landing table id (`raw_landing`) |
| `BQ_STAGING_TABLE` | deploy-time | — | Staging table id (`raw_staging`) |
| `RAW_ARCHIVE_BUCKET` | deploy-time | — | Raw archive bucket the load reads |
| `PUBSUB_TOPIC` | deploy-time | — | Short topic name (`co-events-topic-dev`) |
| `SPEEDUP` | deploy-time, overridable | `86400` | Real seconds of history per wall second |
| `MAX_SLEEP_SECONDS` | deploy-time, overridable | `5` | Clamp on any single inter-record sleep |
| `RUN_LOAD` | execution-time | `false` | `false` = replay only, `only` = load then exit, `true` = load then replay |
| `EVENT_ID` | execution-time | unset | Optional lifecycle event filter (validated against `events.yaml`) |
| `WINDOW_FROM` / `WINDOW_TO` | execution-time | unset | Optional `created_utc` bounds (ISO 8601, `WINDOW_TO` exclusive) |
| `PUBSUB_ENDPOINT` | rarely | regional endpoint | Override for tests |

## Running

Prepare the staging table, then replay fast (100 simulated days per wall second):

```bash
gcloud run jobs execute co-publisher-dev --region=europe-central2 \
  --update-env-vars="RUN_LOAD=only" --wait

gcloud run jobs execute co-publisher-dev --region=europe-central2 \
  --update-env-vars="RUN_LOAD=false,SPEEDUP=8640000,MAX_SLEEP_SECONDS=1" --wait
```

Verify ordering and counts from the manual subscription:

```bash
gcloud pubsub subscriptions pull co-events-verify-sub-dev --limit=100 --auto-ack \
  --format="value(message.attributes.created_utc)"
```

Locally with application-default credentials: export the variables and run `python -m publisher.load` (load only) or `python -m publisher.main`.

## Design notes

- **No checkpoint/resume.** Reruns cost minutes, staging is deduplicated, and downstream consumers dedup by `id`; manual resume exists for free via `WINDOW_FROM=<last published created_utc>`. A checkpoint would add external state and a failure mode disproportionate to the thesis.
- **`max_retries = 0` on the Cloud Run Job.** An automatic retry of a partial replay would double-publish; a rerun is a manual decision.
- **Publish errors** pause the ordering key inside the client; the publisher calls `resume_publish` and retries with bounded backoff, then fails loudly.
- **Shared code.** Only `collectors.common.events_config` is imported (as a submodule, so collector-only dependencies stay out of this image).
