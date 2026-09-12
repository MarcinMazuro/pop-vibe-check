# NLP evaluation

Outline for the DistilBERT chapter. Numbers land here after the gold set
is labelled and scored with the fine-tuned checkpoint.

## 1. Gold set (~300)

**Status (2026-09-12).** Gold labelled; scored with fine-tuned DistilBERT
(local inference). Model Registry upload done; **no Endpoint deploy**.

| Artifact | Path | Rows |
|---|---|---|
| Stratified candidates | `nlp/eval/artifacts/candidates.jsonl` | 300 |
| Labelled gold | `nlp/eval/artifacts/gold.jsonl` | 300 |
| Predictions | `nlp/eval/artifacts/pred.jsonl` | 300 |
| Evaluate report | `nlp/eval/artifacts/report.json` | — |
| Local weights (gitignored) | `nlp/eval/artifacts/distilbert-sent/` | from GCS |

**Sampling.** Usable rows exported from
`pop-vibe-check.co_analytics_dev.raw_staging` via `bq` (text length ≥ 8),
then `python -m nlp.eval.sample_gold` (seed 33, n=300, strata
`source`×`language`). Companion SQL:
`nlp/eval/sql/sample_gold.sql`.

**Labels.** `pos` / `neu` / `neg` per `nlp/eval/GUIDELINES.md`
(sentiment toward the game/event). Text-by-text **assistant-assisted**
pass on the real YouTube comments (not random). Distribution:

| Label | n | holdout | train |
|---|---|---|---|
| pos | 161 | 36 | 125 |
| neu | 119 | 36 | 83 |
| neg | 20 | 8 | 12 |
| **total** | **300** | **80** | **220** |

Hold-out is ≥ 80 and must not enter `--own-domain` fine-tuning.

**Predictions.** Fine-tuned DistilBERT from
`gs://co-tf-artifacts-dev/nlp/models/distilbert-sent/` (downloaded to the
gitignored local path above; CPU inference, `MAX_LEN=128`).

**DistilBERT metrics** (`nlp/eval/artifacts/report.json`):

| Slice | n | accuracy | macro-F1 | F1 pos / neu / neg |
|---|---|---|---|---|
| overall | 300 | **0.533** | **0.472** | 0.642 / 0.420 / 0.353 |
| holdout | 80 | 0.525 | 0.498 | 0.633 / 0.407 / 0.455 |
| train | 220 | 0.536 | 0.458 | 0.645 / 0.425 / 0.304 |

Earlier stub-keyword baseline on the same gold (replaced): accuracy 0.417,
macro-F1 0.363. Per-language / per-source slices remain in the report JSON.
English DistilBERT on non-EN / langdetect-noise tags is a **measured
limit**, not a quality target.

**Vertex Model Registry** (upload only; no replica):

`projects/891032629527/locations/europe-central2/models/6682862459948105728`
(`displayName=distilbert-sent`, region `europe-central2`). Artifact URI
still `gs://co-tf-artifacts-dev/nlp/models/distilbert-sent`. Serving
container used at upload:
`europe-docker.pkg.dev/vertex-ai/prediction/huggingface-pytorch-inference-cpu.2-3:latest`
(HF layout; the TorchServe `pytorch-cpu` image expects `.mar` and was
rejected).

```bash
python -m nlp.eval.evaluate \
  --gold nlp/eval/artifacts/gold.jsonl \
  --pred nlp/eval/artifacts/pred.jsonl \
  --output nlp/eval/artifacts/report.json
```

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
Local eval copies under `nlp/eval/artifacts/distilbert-sent/` are
gitignored.
