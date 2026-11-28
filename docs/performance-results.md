# Performance, scalability and cost — results and history

What the experiments planned in [performance-plan.md](performance-plan.md)
found, and how we got there — including the attempts that did not work,
because they explain why the final method looks the way it does. Tooling:
[`perf/`](../perf/README.md). Raw results: BigQuery
`co_analytics_dev.perf_runs` / `perf_timeseries` and
[`perf/results/`](../perf/results/).

Dates: 2026-11-21/22 (E1), 2026-11-28 (E3). Times are UTC unless stated
otherwise. Owner: Oskar.

---

## Summary

- **The pipeline scales.** With a full backlog and the stub classifier,
  fixed `e2-standard-2` workers process about **345 / 480 / 970 records/s
  with 1 / 2 / 4 workers** (≈ 1.4× from one to two workers, ≈ 2.0× from
  two to four).
- **The replay publisher, not the pipeline, limits a normal replay** to
  about **50 records/s**: it publishes on one global ordering key and waits
  for every publish to be acknowledged. That is a deliberate trade —
  exact chronological order for input rate — and adding workers behind it
  only adds cost (1 → 2 workers: same 50 rec/s, double the cost).
- **Headroom.** Real traffic for this release peaked below 1 record/s;
  one worker has more than 300× headroom.
- **Cost.** About **0.00024–0.00037 USD per 1,000 records** when the
  pipeline runs at capacity (list prices, Warsaw). Behind the 50 rec/s
  publisher the same work cost 0.0011–0.0024 USD per 1,000 records,
  because the workers mostly waited. Roughly 10 minutes of every short job
  is fixed start/stop time, which dominates the cost of small runs.
- **Delivery order does not change results.** The same 256,570 records
  processed in chronological order and heavily shuffled produced
  **identical labels, scores and languages for every record**.
- **Correctness under load.** Every run landed exactly the expected
  number of distinct ids, with no duplicates.
- **With the real model the model is the limit (E3).** XLM-RoBERTa on
  one CPU-only `n2-standard-8` Vertex replica classifies about
  **20 records/s** (replica CPU ~82 %, ~5 s per predict call), about 24×
  slower than the same two workers with the stub. That is still about
  **24× the real peak**. Cost about **0.021 USD per 1,000 records**, three
  quarters of it the replica.
- **Same labels as production.** The E3 run reproduced the stored label
  for 8,804 of 8,805 records (mean score difference 0.00003).
- The experiments themselves cost about **1.35 USD** (E1) plus
  **~0.5 USD** (E3).

The E1 capacity numbers are for the **stub** classifier: they measure the
pipeline, not the model. The model is measured in E3.

---

## Setup

**What runs.** Each experiment is the normal replay build
(`dataflow/replay.cloudbuild.yaml`) with experiment parameters — chosen
because it always drains its streaming Dataflow job, even when a run
fails. Dataflow: Streaming Engine on, `e2-standard-2` workers (2 vCPU),
classifier `stub`.

**Isolation.** Experiments write `events_landing_perf` and read amplified
data from `raw_staging_perf`, never the real tables: `promote.sql` merges
all of `events_landing` into `events`, so experiment rows there would leak
into the analytics at the next real replay (synthetic ids inserted, real
labels overwritten by fresher stub labels). Nothing is promoted. The four
perf tables were created by hand ahead of Terraform (`perf/sql/
create_tables.sql`) and are defined in `terraform/modules/bigquery/perf.tf`.

**Data.** The launch week, 2025-04-24 to 2025-04-30: **25,657 records**.
For sustained load it was amplified ×10 (`perf/amplify.py`: ten copies
with ids suffixed `#perf<n>`, timestamps unchanged) to **256,570 records**.
Nothing in the system caches predictions, so every copy is a real
classification.

**Measurements.** Per run (`perf/collect.py`): records landed and
distinct ids; per-minute throughput from `processed_at`; Cloud Monitoring
series (vCPUs, system lag, data watermark age, subscription backlog and
oldest unacked message age); resource usage from the
`dataflow.googleapis.com/job/total_*` metrics; cost from
`perf/prices.yaml`.

**Prices.** Read from the Cloud Billing Catalog API on 2026-11-22 (SKUs
effective 2026-11-21), Warsaw list prices in USD: streaming vCPU 0.0828 /h,
RAM 0.004268 /GiB·h, standard PD 0.000065 /GiB·h, Streaming Engine data
0.02178 /GiB; Vertex n1-standard-8 replica **0.636 /h** including the
management fee (the ~0.38 /h quoted in `phase-1-steam-collection.md`
leaves the fee out). E3 served on `n2-standard-8` (8 vCPU, 32 GiB): same
per-unit prices as N1 (catalog read 2026-11-28), **0.651 /h** per replica.

---

## History

### 1. Past replays and real traffic (E0) — read-only

From `processed_at` in `events_landing`, earlier replays ran at **~33
records/s** with the real model (the full 263,893 records in 2 h 12 min)
and 20–40 records/s with the stub. From `created_utc` in `raw_staging`,
real traffic peaked at **0.82 records/s** (YouTube, one minute) and 0.5/s
(Steam). The Dataflow job history of those replays had already expired
(about 30 days), so worker counts could not be reconstructed — which is
why `collect.py` copies every metric into BigQuery right after a run.
Details and queries: [performance-plan.md](performance-plan.md).

### 2. Getting the tooling to run from Windows

The experiments are started from a Windows laptop. Before the first
successful run three problems had to be fixed:

- **`bq` cut multi-line SQL.** On Windows `bq` and `gcloud` are `.cmd`
  wrappers, and `cmd.exe` cuts an argument at its first newline:
  `perf/amplify.py`'s script ran only its `TRUNCATE`. SQL now always goes
  to `bq` on standard input, and `amplify` checks the row count it wrote.
- **`cmd.exe` ate the carets** of gcloud's `^~^KEY=v~KEY=v` substitution
  syntax (needed because job labels contain commas). Arguments with cmd
  metacharacters are now double-quoted.
- **`Permission denied` on `dataflow/launch.sh`.** `gcloud builds submit`
  from a Windows working tree uploads scripts without the executable bit
  (build `ebdf32ca`, failed before creating a job). The replay build now
  runs `bash dataflow/launch.sh` / `bash dataflow/promote.sh`, which works
  from either source.

### 3. First run on real data — 53 records/s, one worker

`e1-w2-lw-r1`: the launch week once (25,657 records), up to 2 workers.
Every record landed; **53 rec/s mean, 92 peak, 0.03 USD**. The autoscaler
never added the second worker: the publisher sent most records in the
first minutes, the backlog peaked at 5,061 messages (oldest 100 s) and one
worker cleared it in about five minutes.

The collector first reported a cost of zero: `gcloud beta dataflow
metrics list` returns watermark and lag figures for streaming jobs, but
no resource usage. Resource usage now comes from Cloud Monitoring's
`job/total_*` metrics.

### 4. Fixed workers on ten times the data — still ~50 records/s

To compare worker counts, `NUM_WORKERS` was added (`--num-workers`,
autoscaling off), and the launch week amplified ×10.

| Run | Workers | Mean | Peak | Job | Cost |
|---|---|---|---|---|---|
| `e1-n1-x10` | 1 | 51.5 rec/s | 98 | 89 min | 0.29 USD |
| `e1-n2-x10` | 2 | 49.7 rec/s | 137 | 92 min | 0.61 USD |

The second worker changed nothing but the bill. The subscription backlog
stayed near empty (median ~70–100 messages, oldest unacked ~1–2 s): the
pipeline was waiting for input. The cause is in `publisher/replay.py`:
one ordering key (`"global"`) and `future.result()` after every publish,
so publishing is strictly serial — about 50 messages/s. That is by design
(global chronological order is a stated requirement in
`architecture.md`), but it means these runs measured the publisher.

The laptop went to sleep during this series. The loop that starts the
runs is local, so the 4-worker run never started — deliberately not
re-run, since it would have shown the same 50 rec/s at four times the
cost. The 2-worker run itself was unaffected: its build ran in Cloud
Build, finished and drained the job.

### 5. A load generator on the laptop — ~15 records/s

`perf/loadgen.py` publishes the same messages (built by the publisher's
own `build_message` from the same staging rows) unordered and batched,
started by `run.py` once the job is running. Locally it read and encoded
about 13,000 rows/s from BigQuery — but Pub/Sub accepted only **~15
messages/s** from the laptop (topic `send_message_operation_count`),
worse than the publisher. The bottleneck was publishing from a home
connection with the Python client on Windows.

The run (`e1-n1-lg-x10`, build `1f230f2a`, job
`2026-11-22_01_56_37-6675854103178013656`) was aborted after about 40
minutes with 29,158 records landed: generator stopped, job drained,
subscription purged (seek to now) so nothing could leak into a real
replay, build cancelled. No result was recorded.

### 6. Prefilling the subscription from Cloud Build — the method that works

If the backlog is full before the job starts, the job drains it at its own
maximum rate and the publish rate stops mattering. `perf/run.py
--load-source prefill`:

1. refuses to start while any Dataflow job is running (a real replay would
   take the experiment's messages);
2. purges the subscription;
3. runs `perf/prefill.cloudbuild.yaml`, which runs the load generator
   inside Cloud Build — about **2.5 minutes for 256,570 messages**;
4. starts the replay build with the publisher skipped
   (`_PUBLISHER_MODE=external`); its wait and drain steps run as usual;
5. purges the subscription again if anything fails.

The Cloud Build service account had no right to publish, so it was given
`roles/pubsub.publisher` on the events topic only — by hand
(2026-11-22) and in Terraform (`perf_publisher_emails` in the pubsub
module, empty by default so prod grants nothing). The first prefill
(build `89a53abf`) failed before publishing anything: the publisher's code
imports `collectors.common`, which needs PyYAML; the build now installs
`publisher/requirements.txt`.

### 7. The real model (E3) — one replica, a smaller data set

**Serving machine.** The project's quota for N1 custom-model-serving CPUs
is used up (8/8, see [phase-1-nlp-vertex-dev.md](phase-1-nlp-vertex-dev.md)),
so the model was served on `n2-standard-8` (quota free). Model
`xlmr-sent-v2.1` (registry version 2, the one behind `events`), one
replica, no accelerator, deployed with `gcloud ai endpoints deploy-model`
(the local environment lacked the Vertex SDK that
`nlp/endpoint/register.py` uses; the parameters are the same). The deploy
took about 15 minutes.

**Data.** Earlier notes put the model at roughly 6 records/s on one
`n1-standard-8` replica ([phase-1-steam-collection.md](phase-1-steam-collection.md)),
which would make the whole launch week (25,657 records) a 70-minute
drain. A steady state needs only a few minutes, so the run used the first
two launch days, 2025-04-24 and 25: **8,805 records**, no amplification.

**First attempt failed before starting a job** (`e3-r1-pf`, build
`d1411028`): `dataflow/launch.sh: line 34: $'\r': command not found`. The
repository stores the script with LF line endings, but a Windows checkout
with `core.autocrlf=true` writes CRLF, and `gcloud builds submit` uploads
the working tree as it is. The E1 runs had used a checkout with LF. The
subscription was purged by `run.py`; the replica was the only cost. With
the working copy converted back to LF the second attempt ran. A
`.gitattributes` rule (`*.sh text eol=lf`) would prevent this for
everyone building from Windows.

**Undeploy.** The model was undeployed right after the job drained and
the endpoint checked empty; the replica was up for about 40 minutes.

---

## Results — pipeline capacity (E1)

Launch week ×10, prefilled backlog, stub classifier, fixed workers.

| Run | Workers (vCPU) | Steady state | Peak | Mean incl. ramp | Active | Job | Cost | Cost / 1,000 rec |
|---|---|---|---|---|---|---|---|---|
| `e1-n1-pf-x10` | 1 (2) | **~345 rec/s** | 351 | 329 | 13 min | 23 min | 0.061 USD | 0.00024 USD |
| `e1-n2-pf-x10` | 2 (4) | **~480 rec/s** | 488 | 428 | 10 min | 19 min | 0.094 USD | 0.00037 USD |
| `e1-n4-pf-x10` | 4 (8) | **~970 rec/s** | 978 | 713 | 6 min | 14 min | 0.092 USD | 0.00036 USD |

Records per second, per minute (first and last minutes are partial):

```
1 worker : 288 321 338 344 348 344 350 351 348 345 340 349 210
2 workers: 297 465 478 483 485 479 478 484 488 138
4 workers: 520 963 976 978 831   8
```

Every run landed 256,570 / 256,570 distinct ids with no duplicates, and
ran at the requested worker count throughout (Monitoring
`current_num_vcpus` = 2 / 4 / 8).

**Reading it.**

- Steady-state throughput grows with workers: ×1.4 from one to two, ×2.0
  from two to four, ×2.8 overall. Why the first step is smaller is not
  established — one run per configuration is not enough to separate a
  real effect from run-to-run variation.
- About 8–10 minutes of every job is start-up and drain. For a run this
  short that fixed time dominates, which is why four workers cost no more
  than two: they finished sooner.
- Against real traffic (< 1 record/s at the launch peak) a single worker
  has more than 300× headroom; even the ordered publisher's 50 rec/s is
  50× the real peak.

## Results — the real model (E3)

First two launch days (8,805 records), prefilled backlog, 2 fixed
`e2-standard-2` workers, `xlmr-sent-v2.1` on one `n2-standard-8` Vertex
replica (CPU only), default `max_batch_size` 200.

| Run | Steady state | Peak | Mean incl. ramp | Active | Job | Cost | Cost / 1,000 rec |
|---|---|---|---|---|---|---|---|
| `e3-r2-pf` | **~19.8 rec/s** | 20.5 | 18.3 | 8 min | 15 min | 0.183 USD | 0.021 USD |

Records per minute (first minute partial):

```
430 1189 1232 1189 1190 1195 1199 1181
```

8,805 / 8,805 distinct ids landed, no duplicates.

**Where the time goes.** The replica's CPU utilisation stayed at ~82 %
and a predict call took a median of ~5 s (max ~9.5 s) — the model is the
bottleneck, not the pipeline. Two workers that move ~480 rec/s with the
stub (E1) move ~20 rec/s with the model: a factor of about 24. One
replica of 8 vCPU handles one record per ~50 ms. Adding Dataflow workers
would not help; adding replicas (or splitting traffic across machine
families, as `phase-1-nlp-vertex-dev.md` suggests) should scale roughly
linearly, which is consistent with the ~33 rec/s of the earlier full
replay (E0) — not measured here.

**Cost.** Of the 0.183 USD, 0.141 is the replica for the 13 minutes of
the job (0.217 replica-hours) and 0.042 the Dataflow job. The replica
dominates, and it bills for as long as it is deployed, not per request:
the deploy and the minutes around the run cost more than the run itself.
At steady state the replica alone is about **0.009 USD per 1,000
records** (0.651 USD/h ÷ ~71,000 records/h).

**Headroom.** ~20 rec/s against a real peak of 0.82 rec/s: about 24×
with one replica, so one replica would keep up with live traffic for this
release; a full replay of 263,893 records would take about 3.7 hours.

**Correctness.** Labels from this run against the stored labels in
`events` (same records, same model version from the earlier production
replay): **8,804 / 8,805 identical**, mean absolute score difference
0.00003 — numerical noise of CPU inference on a different machine type.

## Order independence

Does unordered delivery (prefill, load generator) change what the
pipeline produces? The pipeline classifies every record independently —
no windowing or aggregation in Beam (`dataflow/pipeline.py`); aggregates
are computed later in BigQuery — so it should not. Checked on the same
256,570 ids processed by the ordered publisher run (`e1-n1-x10`) and the
shuffled prefill run (`e1-n1-pf-x10`):

| | Ordered (publisher) | Shuffled (prefill) |
|---|---|---|
| Rank correlation, `created_utc` vs `processed_at` | 1.00 | 0.17 |
| Mean displacement of a record in the processing order | 0.02 % of the set | 30 % of the set |
| Same `sentiment_label` | | **256,570 / 256,570** |
| Same `sentiment_score` | | 256,570 / 256,570 |
| Same `language` | | 256,570 / 256,570 |

The stub and the language detector are deterministic, so identical output
is expected; the check confirms the pipeline introduces no order
dependence of its own. It holds for the pipeline as it is — a future
event-time windowed aggregation in Beam would need its own check for late
data.

---

## Cost of the experiments

| Item | USD |
|---|---|
| E1 recorded runs | 1.18 |
| Aborted laptop load-generator run (~40 min, 1 worker, estimate) | ~0.15 |
| Failed builds, prefill builds, BigQuery queries | < 0.05 |
| **E1 total** | **~1.35** |
| E3 Dataflow job (`e3-r2-pf`) | 0.04 |
| E3 Vertex replica, deployed ~40 min (estimate, 0.651 USD/h) | ~0.4–0.45 |
| **E3 total** | **~0.5** |

## Limitations

- **E1 used the stub classifier** — the capacity of the pipeline. The
  system with the model (E3) was measured once, on one replica, one
  machine type and the default batch size; scaling with replicas is
  expected, not measured.
- **One run per configuration.** Enough to show the scaling trend, not to
  give confidence intervals or explain the 1→2 worker step.
- **One machine type** (`e2-standard-2`), one region, fixed workers; the
  autoscaler was observed (section 3), not characterised.
- **Latency** is only what Dataflow and Pub/Sub report (system lag,
  oldest unacked message age); no per-record publish-to-write delay.
- **Cost is an estimate** from resource usage and list prices; no billing
  export exists to check it. Streaming Engine was priced by data
  processed; jobs on resource-based billing are charged in Streaming
  Engine Compute Units instead (`job/total_secu_usage` is recorded).

## Still to do

- **E6** — cost model: per 1,000 records, a whole replay, always-on
  versus on-demand, and a 10× / 100× larger release.

Dropped as not needed for the thesis: an ordered fast load generator
(order does not change results), a separate latency series (E4; latency
comes from every run's metrics) and an autoscaling series (E2).

---

## Reproduction

Runs (`perf/results/specs/` holds each run's exact parameters):

| Run | Build | Dataflow job | Code |
|---|---|---|---|
| `e1-w2-lw-r1` | `de299055-7047-4912-aca2-1e96746f498c` | `2026-11-21_17_28_39-4797360834238293472` | `915c8f1` |
| `e1-n1-x10` | `6b8e0f62-965a-43cc-b873-a80e65550572` | `2026-11-21_17_54_47-13475255881541283443` | `f06e4ea` |
| `e1-n2-x10` | `65b68130-8f8b-4839-983d-f967a02f6d05` | `2026-11-21_19_28_23-16627903273842528296` | `f06e4ea` |
| `e1-n1-pf-x10` | `2d8aecea-db7e-4f91-80fe-6d15ebb2e468` | `2026-11-22_02_56_35-4303834219557585980` | `7d3fa29` |
| `e1-n2-pf-x10` | `8fa531a9-6d6c-408d-b64a-d36497282302` | `2026-11-22_03_25_16-4554390494456002706` | `7d3fa29` |
| `e1-n4-pf-x10` | `d9c2015e-42e7-440b-947d-80b351766c20` | `2026-11-22_03_51_02-3613154027607251332` | `7d3fa29` |

The `-dirty` suffix on the last two runs' recorded commit comes from
result files written earlier in the same series, not from code changes.

The capacity series, from the repo root:

```bash
python -m perf.amplify --copies 10 --from 2025-04-24 --to 2025-05-01
for n in 1 2 4; do
  python -m perf.run --experiment e1 --run-id "e1-n$n-pf-x10" --model stub \
    --num-workers "$n" --staging-table raw_staging_perf --copies 10 \
    --load-source prefill --wait-timeout-minutes 120 --yes
done
```

Order check (BigQuery):

```sql
WITH a AS (
  SELECT id, ANY_VALUE(sentiment_label) l, ANY_VALUE(sentiment_score) s,
         ANY_VALUE(language) lang
  FROM `pop-vibe-check.co_analytics_dev.events_landing_perf`
  WHERE processed_at BETWEEN '2026-11-22T01:54:00Z' AND '2026-11-22T03:25:00Z'
  GROUP BY id),
b AS (
  SELECT id, ANY_VALUE(sentiment_label) l, ANY_VALUE(sentiment_score) s,
         ANY_VALUE(language) lang
  FROM `pop-vibe-check.co_analytics_dev.events_landing_perf`
  WHERE processed_at BETWEEN '2026-11-22T10:56:00Z' AND '2026-11-22T11:21:00Z'
  GROUP BY id)
SELECT COUNT(*) AS ids, COUNTIF(a.l = b.l) AS same_label,
       COUNTIF(a.s = b.s) AS same_score,
       COUNTIF(a.lang IS NOT DISTINCT FROM b.lang) AS same_language
FROM a JOIN b USING (id);
```
