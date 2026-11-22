# Performance, scalability and cost — evaluation plan

How fast the pipeline goes, where it stops scaling, what it costs, and
whether it stays correct under load. This is the evidence for the
"scalable system" in the thesis goal, and the source of the thesis
section on performance and cost.

Date: 2026-11-22. Owner: Oskar.

---

## What is already known

### Throughput of past replays (E0)

Measured from `processed_at` in `co_analytics_dev.events_landing`, one
run = processing with no gap longer than 10 minutes. Query in the
appendix; it reads ~17 MB.

| Classifier | Date | Records | Active minutes | Mean rec/s | Peak rec/s (1-min) |
|---|---|---|---|---|---|
| `stub/1` | 2026-09-05 | 8,456 | 7 | 20.1 | 39.2 |
| `stub/1` | 2026-09-20 | 4,228–12,254 | 2–5 | 35.2–40.8 | 37.1–69.7 |
| Vertex (first tests) | 2026-09-21 | 991–14,001 | 2–14 | 8.3–18.5 | 14.1–24.6 |
| Vertex, two model versions side by side | 2026-10-17 | 131,789 + 132,104 | 133 | 16.5 + 16.6 | 24.2 / 23.7 |
| `xlmr-sent-v2.1` | 2026-10-18 | 263,893 | 132 | 33.3 | 49.2 |

The full dataset goes through in about 2 h 12 min at ~33 records/s. On
2026-10-17 two model versions shared the traffic at ~16.5 rec/s each —
~33 rec/s in total again — which points at a limit outside the model
(publisher pace, Dataflow at `MAX_WORKERS=2` × `e2-standard-2`, or the
endpoint replica count). That is a lead, not a finding: the Dataflow job
history for those runs has expired (completed jobs are listed for about
30 days), so worker counts and autoscaling cannot be reconstructed.

### Real-world arrival rate

From `created_utc` in `co_analytics_dev.raw_staging`:

| Source | Records | Peak per minute | Peak per hour |
|---|---|---|---|
| Steam | 251,639 | 30 (0.50/s) | 812 (0.23/s) |
| YouTube | 12,254 | 49 (0.82/s) | 691 (0.19/s) |

Real traffic never exceeds about one record per second, even on launch
day. At ~33 rec/s the pipeline has roughly 40× headroom for this
release. So the useful question is not "does it keep up with Clair
Obscur" but **how large a release it could carry**, and at what cost.

### Is there enough data?

Load comes from time compression (`SPEEDUP`), so what matters is how long
263,893 records last at a given rate:

| Rate | Duration of one full replay |
|---|---|
| 33 rec/s | 2 h 12 min |
| 300 rec/s | ~15 min — still enough for a steady-state measurement |
| 1,000 rec/s | ~4 min — too short |

Up to ~300 rec/s the real dataset is enough. Above that, the data has to
be amplified: copies of the records with new ids (the pipeline
deduplicates on `id`), written to a separate staging table so the real
one stays untouched.

### Cost visibility

- No billing export to BigQuery exists, and the team members' accounts
  without billing-account roles cannot see costs.
- A billing export only collects data from the moment it is enabled, so
  it has to be switched on **before** the experiments.

---

## Questions

1. **Capacity.** Maximum sustained throughput of the pipeline without the
   model, and how it scales with workers.
2. **Bottleneck.** With the real model: endpoint replicas, batch size, or
   the publisher?
3. **Latency.** Publish-to-BigQuery delay at different loads.
4. **Elasticity.** How autoscaling reacts to a step in load, and how fast.
5. **Cost.** Per 1,000 records, per full replay, per month always-on
   versus on-demand; projection for a 10× and 100× larger release.
6. **Correctness under load.** No records lost or duplicated at the
   highest load.

---

## Experiments

| | What | Varied | Measured |
|---|---|---|---|
| E0 | Past replays — **done** | — | ~33 rec/s, see above |
| E1 | Pipeline with the `stub` classifier (no Vertex cost) | `MAX_WORKERS` 1 / 2 / 4 × increasing `SPEEDUP` | highest rate at which the subscription backlog stays flat |
| E2 | `stub`, autoscaling, step load | load profile (flat → step up → step down) | vCPUs over time, time to scale up and down |
| E3 | Real model on the Vertex Endpoint | replicas 1 / 2 / 4 × `max_batch_size` | throughput, cost per 1,000 records |
| E4 | Latency | 25 / 50 / 75 / 90 % of the E1/E3 maximum | data freshness, oldest unacked message age |
| E5 | Correctness | highest sustainable load | row counts, `dataflow/verify.sql` fingerprint, DLQ count |
| E6 | Cost model | analysis | cost per 1,000 records, per replay, per month; 10× / 100× projection |

Order: preparation → E1 → E3 → E2 and E4 → E5 → E6.

**Latency without touching the pipeline.** E4 starts from Dataflow's own
metrics (data freshness, system lag) and Pub/Sub's oldest unacked
message age. An exact per-record publish-to-write delay needs the Pub/Sub
publish time written next to `processed_at` — a small change to
`dataflow/transforms.py` and the `events_landing` schema, done only if
the built-in metrics are not precise enough.

---

## What gets built

Built in [`perf/`](../perf/README.md); the summary below is the design.

- **Experiment runner.** One command per run, wrapping
  `dataflow/launch.sh` and the replay publisher: `SPEEDUP`,
  `MAX_WORKERS`, `MACHINE_TYPE`, model, `max_batch_size`, replica count.
  Every Dataflow job gets labels (`experiment=e1`, `run=…`) so the
  billing export can attribute cost to a run.
- **Metrics collector.** Run right after each experiment: pulls the
  Dataflow job metrics (vCPU time, memory, Streaming Engine data) and the
  Cloud Monitoring time series (throughput, backlog, freshness, vCPUs,
  endpoint replicas and latency) into a BigQuery table of runs. This is
  not optional — Dataflow history disappears after about 30 days, which
  is why E0 has no worker data.
- **Data amplifier.** For runs above ~300 rec/s: copies of the staging
  records with new ids into a separate table.
- **Analysis.** Queries and charts for the thesis.

## Cost, two ways

1. **From resource usage** — no billing access needed: Dataflow vCPU-hours,
   memory GB-hours and Streaming Engine data from the job metrics, plus
   endpoint node-hours and Pub/Sub volume, priced with the public price
   list for `europe-central2`.
2. **From the billing export** — to check method 1. Needs someone with a
   billing-account role to enable the export into a BigQuery dataset and
   grant read access to it.

## Budget

A Vertex replica (`n1-standard-8`) is about $0.38/h
([phase-1-steam-collection.md](phase-1-steam-collection.md)); one run is
15–20 minutes. The whole plan is in the order of tens of PLN up to about
150 PLN; E1 gives a measured figure to refine this. The project budget
alert is 50 PLN a month, so either spread the runs over time or raise the
alert threshold for the experiment period.

## Risks

- **Quotas.** Dataflow vCPU and Vertex quotas in `europe-central2` may cap
  E1 and E3 before the pipeline does.
- **Shared environment.** Experiments use the same dev pipeline and
  subscription as replays, so announce runs and never overlap one with a
  replay. They must **not** write `events_landing`: `dataflow/promote.sql`
  merges all of it into `events`, so experiment rows would leak into the
  analytics at the next real replay (synthetic ids inserted, real labels
  overwritten by fresher stub labels). `_PROMOTE=false` alone does not
  prevent that. Experiments therefore write `events_landing_perf` and read
  amplified data from `raw_staging_perf` — see `perf/README.md`.
- **Endpoint left running.** The endpoint costs money while a model is
  deployed. Undeploy after every E3 session (`enable_nlp_endpoint`).

---

## Appendix — queries

Throughput per past run (E0):

```sql
WITH gaps AS (
  SELECT model_version, processed_at,
    IF(TIMESTAMP_DIFF(processed_at,
         LAG(processed_at) OVER (PARTITION BY model_version ORDER BY processed_at),
         MINUTE) > 10, 1, 0) AS new_run
  FROM `pop-vibe-check.co_analytics_dev.events_landing`),
runs AS (
  SELECT model_version, processed_at,
    SUM(new_run) OVER (PARTITION BY model_version ORDER BY processed_at) AS run_id
  FROM gaps),
per_min AS (
  SELECT model_version, run_id, TIMESTAMP_TRUNC(processed_at, MINUTE) AS m, COUNT(*) AS n
  FROM runs GROUP BY 1, 2, 3)
SELECT model_version, run_id, MIN(m) AS start_min, SUM(n) AS rows_total,
  COUNT(*) AS active_minutes,
  ROUND(SUM(n) / COUNT(*) / 60, 1) AS avg_rows_per_s,
  ROUND(APPROX_QUANTILES(n, 100)[OFFSET(50)] / 60, 1) AS p50_rows_per_s,
  ROUND(MAX(n) / 60, 1) AS peak_rows_per_s
FROM per_min GROUP BY 1, 2 HAVING rows_total > 500 ORDER BY start_min;
```

Real-world arrival rate:

```sql
WITH per_min AS (
  SELECT source, TIMESTAMP_TRUNC(created_utc, MINUTE) AS m, COUNT(*) AS n
  FROM `pop-vibe-check.co_analytics_dev.raw_staging` GROUP BY 1, 2),
per_hour AS (
  SELECT source, TIMESTAMP_TRUNC(created_utc, HOUR) AS h, COUNT(*) AS n
  FROM `pop-vibe-check.co_analytics_dev.raw_staging` GROUP BY 1, 2)
SELECT p.source, SUM(p.n) AS records,
  MAX(p.n) AS peak_per_minute,
  (SELECT MAX(n) FROM per_hour WHERE source = p.source) AS peak_per_hour
FROM per_min p GROUP BY p.source;
```
