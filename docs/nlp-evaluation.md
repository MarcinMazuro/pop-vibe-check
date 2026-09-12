# NLP evaluation

Outline for the DistilBERT chapter. Numbers land here after the gold set
is labelled and the first Vertex replay is promoted into `events`.

## 1. Gold set (~300)

**Status (2026-09-12).** Gold set labelled and scored locally.

| Artifact | Path | Rows |
|---|---|---|
| Stratified candidates | `nlp/eval/artifacts/candidates.jsonl` | 300 |
| Labelled gold | `nlp/eval/artifacts/gold.jsonl` | 300 |
| Predictions | `nlp/eval/artifacts/pred.jsonl` | 300 |
| Evaluate report | `nlp/eval/artifacts/report.json` | — |

**Sampling.** Usable rows exported from
`pop-vibe-check.co_analytics_dev.raw_staging` via `bq` (text length ≥ 8),
then `python -m nlp.eval.sample_gold` (seed 33, n=300, strata
`source`×`language`). Companion SQL:
`nlp/eval/sql/sample_gold.sql`.

**Labels.** `pos` / `neu` / `neg` per `nlp/eval/GUIDELINES.md`
(sentiment toward the game/event). Text-by-text assistant-assisted
pass on the real YouTube comments (not random). Distribution:

| Label | n | holdout | train |
|---|---|---|---|
| pos | 161 | 36 | 125 |
| neu | 119 | 36 | 83 |
| neg | 20 | 8 | 12 |
| **total** | **300** | **80** | **220** |

Hold-out is ≥ 80 and must not enter `--own-domain` fine-tuning.

**Predictions (interim).** `pred.jsonl` is the deterministic **stub**
keyword classifier (`nlp/stub`), not fine-tuned DistilBERT. Fine-tuned
weights live on GCS (`gs://co-tf-artifacts-dev/nlp/models/distilbert-sent/`);
`gsutil` was out of scope for this pass. Re-score after a Vertex CPU
deploy or a local weight download.

**Stub metrics** (`nlp/eval/artifacts/report.json`):

| Metric | Value |
|---|---|
| accuracy | 0.417 |
| macro-F1 | 0.363 |
| F1 pos / neu / neg | 0.540 / 0.381 / 0.168 |

Treat these as a harness baseline, not DistilBERT quality. Per-language
and per-source slices are in the report JSON.

```bash
python -m nlp.eval.evaluate \
  --gold nlp/eval/artifacts/gold.jsonl \
  --pred nlp/eval/artifacts/pred.jsonl \
  --output nlp/eval/artifacts/report.json
```

English DistilBERT on FR/ZH/RU/KO (and langdetect noise tags in the
sample) is a **measured limit**, not a quality target.

## 2. Time windows (SQL on `events`)

`nlp/eval/sql/time_windows.sql` — launch `2025-04-24`:

| Window | Interval (UTC, half-open) |
|---|---|
| week before | [launch − 7d, launch) |
| launch day | [launch, launch + 1d) |
| 48 hours | [launch, launch + 48h) |
| week after | [launch, launch + 7d) |

Also group by `event_tag` from `collectors/config/events.yaml` so the
calendar (reveal, trailer, demo, controversy, TGA) is visible next to
the launch spike.

Run only after `dataflow/promote.sh` has merged `events_landing` →
`events`.

## 3. External baselines

Hand-filled CSVs in `nlp/eval/external/`:

- Metacritic metascore / user score
- OpenCritic top critic / percent recommended
- Steam Charts (or Steam Spy) player counts

Join on `date_utc` against the window aggregates (mean polarity vs
critic score vs CCU). Steam collector rows can replace the Charts CSV
later; they do not block YouTube gold.

## 4. Looker (C4, after the first MERGE)

Authorized views over `events` in `terraform/modules/bigquery` — **not
in this change**. Wait until `model_version` on real rows is a Vertex
id (`vertex/…`), not `stub/1`.

## 5. Reproducibility

The gold JSONL, the evaluate report, and the SQL outputs are the
artifacts. Model weights live in MLflow (`gs://co-tf-artifacts-dev/nlp/mlruns`)
and Vertex Model Registry; they are not copied into the Dataflow image.
