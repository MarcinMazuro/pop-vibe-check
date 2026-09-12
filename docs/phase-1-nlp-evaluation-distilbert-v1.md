# Phase 1 — NLP evaluation (DistilBERT v1)

First fine-tuned sentiment model in phase 1:
English DistilBERT (`distilbert-base-uncased`, 3-class `pos`/`neu`/`neg`).
This document is **evaluation only** — gold set, metrics, time windows,
and external baselines. Infra and Vertex ops live in
[`phase-1-nlp-vertex-dev.md`](phase-1-nlp-vertex-dev.md).

Date: 2026-09-12.

---

## 1. Gold set (~300)

**Status.** Gold labelled; scored with fine-tuned DistilBERT v1 (local
CPU inference on the checkpoint under
`gs://co-tf-artifacts-dev/nlp/models/distilbert-sent/`).

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

**Predictions.** DistilBERT v1, `MAX_LEN=128`, CPU.

**DistilBERT v1 metrics** (`nlp/eval/artifacts/report.json`):

| Slice | n | accuracy | macro-F1 | F1 pos / neu / neg |
|---|---|---|---|---|
| overall | 300 | **0.533** | **0.472** | 0.642 / 0.420 / 0.353 |
| holdout | 80 | 0.525 | 0.498 | 0.633 / 0.407 / 0.455 |
| train | 220 | 0.536 | 0.458 | 0.645 / 0.425 / 0.304 |

Earlier stub-keyword baseline on the same gold (replaced): accuracy 0.417,
macro-F1 0.363. Per-language / per-source slices remain in the report JSON
(EN-only accuracy ≈ 0.635). English DistilBERT on non-EN /
langdetect-noise tags is a **measured limit**, not a quality target.

```bash
python -m nlp.eval.evaluate \
  --gold nlp/eval/artifacts/gold.jsonl \
  --pred nlp/eval/artifacts/pred.jsonl \
  --output nlp/eval/artifacts/report.json
```

---

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
`events` with a real classifier (`vertex/…`), not only the stub.

---

## 3. External baselines

Hand-filled CSVs in `nlp/eval/external/`:

- Metacritic metascore / user score
- OpenCritic top critic / percent recommended
- Steam Charts (or Steam Spy) player counts

Join on `date_utc` against the window aggregates (mean polarity vs
critic score vs CCU). Steam collector rows can replace the Charts CSV
later; they do not block YouTube gold.

---

## 4. Reproducibility

The gold JSONL, the evaluate report, and the SQL outputs are the
evaluation artifacts. Checkpoint identity for v1: hybrid fine-tune best
epoch 2 (`checkpoint-50060`); weights on GCS / Model Registry (see the
Vertex ops journal). Local eval copies under
`nlp/eval/artifacts/distilbert-sent/` are gitignored.
