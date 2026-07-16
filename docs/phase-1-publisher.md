# Phase 1 — Replay publisher: data-source simulation

First Phase 1 milestone. Builds the "live data source" the streaming
pipeline needs from the historical dataset the collectors produced: the
GCS raw archive is loaded into a deduplicated BigQuery staging table, and
a **publisher** Cloud Run Job replays it to Pub/Sub in global
chronological order with time compression — as if the comments were
arriving in real time. Dataflow + NLP consume the topic in a later PR.

Date: 2026-07-16.

---

## Why

The dataset is historical (12 lifecycle events of *Clair Obscur*,
2024-06 → 2026-04; 4228 YouTube comments already in the raw archive), but
the pipeline is meant to process a live stream. Rather than fake a stream
in Dataflow, the publisher *replays* the real records with their real
inter-arrival gaps compressed by a configurable factor: bursts around
events keep their shape, the dead months between events are skipped. The
result is a convincing, explainable simulation whose ordering is a hard
guarantee, not an accident of delivery.

## What was built

### Terraform

- **`modules/pubsub/`** (new): topic `co-events-topic-dev` and an ordered
  pull subscription `co-events-verify-sub-dev` (`enable_message_ordering
  = true`, never-expiring) for manual verification. Topic-level
  `pubsub.publisher` for the publisher SA. The dead-letter topic is
  deferred to the Dataflow PR — a DLQ is meaningless until a consumer can
  nack.
- **`modules/bigquery/`** (extended): `raw_landing` (unpartitioned,
  truncate-and-load target) and `raw_staging` (deduplicated, DAY
  partition on `created_utc`, clustered by `source, event_tag`), both
  from one shared schema local that mirrors
  `collectors.common.records.build_record`. Publisher gets dataset-level
  `dataEditor` + project-level `jobUser`.
- **`modules/iam/`** (extended): `co-publisher-sa-dev`.
- **`modules/cloud_run_jobs/`** (extended): `co-publisher-dev` job —
  timeout 6 h, `max_retries = 0` (a retried partial replay would
  double-publish), deploy-time env for BQ/topic/pacing, plus
  `storage.objectViewer` on the raw archive (BQ load reads GCS as the
  caller).

### Application (`publisher/`)

New top-level package (the publisher is not a collector). Imports only
`collectors.common.events_config` for `EVENT_ID` validation.

- **`config.py`** — env-driven `RunConfig`, fail-loud like the
  collectors. `RUN_LOAD ∈ {false, only, true}`, `SPEEDUP > 0`,
  `MAX_SLEEP_SECONDS ≥ 0`, optional `EVENT_ID` / `WINDOW_FROM` /
  `WINDOW_TO`.
- **`load.py`** — BQ load job (`gs://bucket/*.jsonl.gz`,
  `WRITE_TRUNCATE`) into `raw_landing`, then a `MERGE` that dedups by
  `id` (freshest `collected_at` wins) into `raw_staging`. Re-running is a
  no-op.
- **`replay.py`** — reads staging `ORDER BY created_utc, id`; per record
  sleeps `min((tᵢ − tᵢ₋₁)/SPEEDUP, MAX_SLEEP_SECONDS)`, then publishes
  the record JSON under the constant ordering key `global`. Publish
  errors pause the ordering key → `resume_publish` + bounded backoff,
  then fail loud.
- **`main.py`** — config → optional load → replay → summary. Publisher
  client uses the regional endpoint (`europe-central2-pubsub...`), which
  Pub/Sub ordering requires.
- 35 unit tests (pacing math, query/message builders, MERGE SQL, config
  validation) — pure functions, no GCP. `pytest` 54 total, `mypy`
  strict, `black`, `ruff` all green.

### Message shape

`data` = the staged record JSON, exactly the 11 collector fields
(timestamps in ISO 8601 `Z`). `attributes` = `source`, `event_tag`,
`created_utc` (original), `replayed_at` (wall clock). Ordering key
`global`.

## Design decisions

- **Single ordering key `global`.** Global chronological order is the
  pipeline's hard requirement; Pub/Sub ordering is per-key, so one
  constant key is the only thing that gives a global guarantee. The
  per-key 1 MB/s ceiling is irrelevant at paced replay throughput.
- **Pacing = scaled gaps + clamp.** Linear compression alone would sleep
  for hours across the months between events; the `MAX_SLEEP_SECONDS`
  clamp collapses those gaps while intra-event bursts (seconds-to-minutes
  apart) compress below the clamp and keep their shape. Wall time is
  bounded by `records × MAX_SLEEP`, independent of the simulated span.
- **Load in the same container** via `RUN_LOAD`, not a separate job — no
  extra SA or shell script, SQL builders unit-testable.
- **No checkpoint/resume.** Reruns cost minutes, staging is idempotent,
  downstream dedups by `id`; manual resume is `WINDOW_FROM=<last ts>`. A
  checkpoint would add external state and a failure mode out of
  proportion to the thesis.

## Deployment (manual image flow — Cloud Build still blocked by IAM)

```
docker build -f publisher/Dockerfile -t \
  europe-central2-docker.pkg.dev/pop-vibe-check/co-images-dev/publisher:2e209f7... .
docker push ...
```

`publisher_image_uri` pinned in `terraform/envs/dev/main.tf`, then
`terraform apply` (10 added, 2 changed: budget in-place, youtube job
client-metadata drift).

Two build iterations: the first image (`f70a08b...`) crashed on startup
because importing any `collectors.common` submodule ran the package
`__init__`, which eagerly imported `gcs_writer` (google-cloud-storage,
not shipped in this image). Fixed by making `write_batch` /
`retry_transient` lazy PEP-562 exports; rebuilt as `2e209f7...`.

## Verification (dev)

1. **Load** — `gcloud run jobs execute co-publisher-dev
   --update-env-vars=RUN_LOAD=only --wait`:
   `raw_landing` = 4228, `raw_staging` = 4228 (= `COUNT(DISTINCT id)`).
   A second load left staging at 4228 — **idempotence confirmed**.
2. **Replay (fast)** — `RUN_LOAD=false,SPEEDUP=8640000,MAX_SLEEP_SECONDS=1`:
   `Replay finished: 4228 records published in 96.4s wall time;
   simulated span 2024-06-09T17:22:56Z .. 2025-06-15T17:10:43Z`.
3. **Ordering + count** — draining `co-events-verify-sub-dev` and reading
   `message.attributes.created_utc` across many `pull` batches: **4228
   messages** drained (8 in a first interactive pull, then 4220), **0
   out-of-order** — timestamps are monotonically non-decreasing across
   the whole stream. First message `2024-06-09T17:22:56Z` matches the
   replay start; last `2025-06-15T17:10:43Z` matches the replay summary's
   simulated-span end. Drained count == published count == staging
   `COUNT(*)` == 4228.

Note: a single ordering key delivers slowly under `gcloud pubsub
subscriptions pull` (small batches per call), so the drain loops many
pulls. Before a re-run, `gcloud pubsub subscriptions seek
co-events-verify-sub-dev --time=<now>` drops any backlog so counts stay
clean.

## Remaining (rest of Phase 1)

1. `dataflow/` module + Beam pipeline consuming `co-events-topic-dev`;
   adds the dead-letter topic and Dataflow worker SA.
2. `bigquery/` `events` table + Looker authorized views.
3. `nlp/stub/` then `nlp/registry/` (MLflow).
4. Optional: unblock Cloud Build (the two IAM grants from
   [phase-0-youtube-first-collection.md](phase-0-youtube-first-collection.md))
   so the publisher image builds in CI instead of by hand.
