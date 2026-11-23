# perf — performance, scalability and cost experiments

Tooling for the experiments in
[docs/performance-plan.md](../docs/performance-plan.md) — results and the
history of how the method was arrived at in
[docs/performance-results.md](../docs/performance-results.md). Run an experiment,
collect its metrics before Dataflow forgets them, estimate its cost, and
amplify the data for loads the real dataset is too small for.

| Module | Does |
|---|---|
| `run.py` | Runs one experiment end to end: submits the replay build with the experiment's parameters, waits, then collects. |
| `collect.py` | Collects one run: throughput and counts, Dataflow service metrics, Cloud Monitoring time series, cost estimate. Writes `perf_runs` / `perf_timeseries` in BigQuery and CSV files in `results/`. |
| `cost.py` | Prices a run's resource usage with `prices.yaml`. |
| `amplify.py` | Rewrites `raw_staging_perf` with *k* copies of `raw_staging` (ids suffixed `#perf<n>`). |
| `loadgen.py` | Load generator: publishes the staged records unordered and batched, optionally at a target rate. The replay publisher caps at ~50 msg/s (one ordering key, a wait per message — E1 measured it), too little to find the pipeline's limit. |
| `keepawake.py` | Stops Windows idle sleep while a run publishes from this machine. |
| `experiment.py` | What a run is (`RunSpec`) and how it maps onto the replay build's substitutions. |
| `sql/` | The E0 query (past replays) and the real-world arrival-rate query. |

## Safety

Experiments never touch the real tables. Every run writes
`events_landing_perf`, never `events_landing`: `dataflow/promote.sql`
merges *all* of `events_landing` into `events`, so experiment rows there
would leak into the analytics at the next real replay — synthetic ids
inserted, real model labels overwritten by fresher stub labels. Runs also
set `_PROMOTE=false` and `_RUN_LOAD=false`, and amplified data lives in
`raw_staging_perf`. `experiment.py` refuses to build a run that writes
anywhere else.

Cost: a run is the replay build (`dataflow/replay.cloudbuild.yaml`), which
always drains its streaming Dataflow job, even when the run fails. A
vertex run additionally needs a deployed endpoint, which bills until it is
undeployed — the runner records the replica count but does not touch the
endpoint.

Load generator: the input subscription is shared with real replays, so
messages nobody consumes would be written by the next real replay. With
`--load-source loadgen`, `run.py` publishes only once the experiment's
job is running, and if publishing fails it drains the job and purges the
subscription (`gcloud pubsub subscriptions seek … --time=now`). The
standalone `python -m perf.loadgen` refuses to run without `--yes` for the
same reason. Keep the machine on and plugged in while it publishes.

## Before the first run

1. **Tables.** `terraform/modules/bigquery/perf.tf` adds `raw_staging_perf`,
   `events_landing_perf`, `perf_runs` and `perf_timeseries`; apply it
   (`co-terraform-apply-dev`, or `terraform apply` in `terraform/envs/dev`).
   Without the results tables, `collect.py` still writes CSV files.
2. **Prices.** `prices.yaml` holds Warsaw list prices read from the Cloud
   Billing Catalog on 2026-11-22; re-read them before quoting a figure.
3. **Billing export** (optional, to check the estimate): someone with a
   billing-account role enables the export to BigQuery. It only records
   from the moment it is enabled.

### Tables created before Terraform

So experiments could start before this branch merged, the four tables were
created on 2026-11-22 with `sql/create_tables.sql` (same schemas, modes,
partitioning and clustering as `perf.tf`; labelled `managed_by=manual`).
After the merge, **import them instead of applying over them** — an apply
would fail on "already exists". In `terraform/envs/dev`:

```bash
for t in raw_staging_perf events_landing_perf perf_runs perf_timeseries; do
  terraform import "module.bigquery.google_bigquery_table.$t" \
    "projects/pop-vibe-check/datasets/co_analytics_dev/tables/$t"
done
terraform plan   # expect in-place label/description updates only, no replacements
```

If the plan shows a table being **replaced**, stop: replacing drops its data
(including `perf_runs`). Export the results first.

The prefill build's publish right was granted the same way, on 2026-11-22
with `gcloud pubsub topics add-iam-policy-binding` (Cloud Build SA,
`roles/pubsub.publisher`, events topic only). Import it too:

```bash
SA=co-cloud-build-sa-dev@pop-vibe-check.iam.gserviceaccount.com
terraform import "module.pubsub.google_pubsub_topic_iam_member.perf_publisher_publish[\"$SA\"]" \
  "projects/pop-vibe-check/topics/co-events-topic-dev roles/pubsub.publisher serviceAccount:$SA"
```

## Running

Python 3.12 with `requests` and `PyYAML` for running and collecting, plus
`google-cloud-bigquery` and `google-cloud-pubsub` only for
`--load-source loadgen` (the prefill build installs its own). `gcloud` and
`bq` logged in to the project. From the repo root:

```bash
# Pipeline capacity (the method that works — docs/performance-results.md):
# amplify, prefill the subscription from Cloud Build, then the job drains
# the full backlog at its own maximum rate. Refuses to start while any
# Dataflow job runs.
python -m perf.amplify --copies 10 --from 2025-04-24 --to 2025-05-01
python -m perf.run --experiment e1 --run-id e1-n2-pf-x10 \
  --model stub --num-workers 2 --load-source prefill \
  --staging-table raw_staging_perf --copies 10

# E3: the real model, same method (deploy the endpoint first, undeploy after)
python -m perf.run --experiment e3 --run-id e3-r1-pf \
  --model vertex --num-workers 2 --load-source prefill \
  --staging-table raw_staging_perf --endpoint-replicas 1

# With the replay publisher instead (the default): ordered, but capped at
# about 50 msg/s, so it measures the publisher, not the pipeline.
python -m perf.run --experiment e1 --run-id e1-n1-x10 \
  --model stub --num-workers 1 --staging-table raw_staging_perf --copies 10

# Re-collect a run (e.g. after creating the results tables)
python -m perf.collect --spec perf/results/specs/e1-n1-pf-x10.json --job-id JOB_ID
```

`--load-source loadgen` (publishing from this machine while the job runs,
optionally at `--target-rps`) exists but reached only ~15 msg/s from a
home connection — see the results document before relying on it.

`run.py` submits the build from the local working tree, so uncommitted
changes are what runs; the recorded `git_commit` is marked `-dirty` then.
Run ids must be unique — the spec of every run is kept in
`results/specs/`.

## Results

- `results/runs.csv` — one row per run (the CSV copy of `perf_runs`).
- `results/timeseries/<run_id>.csv` — the captured time series.
- `results/specs/<run_id>.json` — the exact parameters of each run.

## Tests

```bash
pytest perf/tests
```
