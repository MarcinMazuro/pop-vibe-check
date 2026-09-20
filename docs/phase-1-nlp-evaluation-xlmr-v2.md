# Phase 1 — NLP evaluation (XLM-RoBERTa v2)

Second fine-tuned sentiment model in phase 1:
multilingual XLM-RoBERTa (`xlm-roberta-base`, 3-class `pos`/`neu`/`neg`).
This document is **evaluation only** — gold set, metrics, time windows,
and external baselines. DistilBERT v1 numbers stay in
[`phase-1-nlp-evaluation-distilbert-v1.md`](phase-1-nlp-evaluation-distilbert-v1.md).
The v2 training recipe is
[`phase-1-nlp-multilingual-v2.md`](phase-1-nlp-multilingual-v2.md).
Infra and Vertex ops live in
[`phase-1-nlp-vertex-dev.md`](phase-1-nlp-vertex-dev.md).

Date: 2026-09-17.

---

## 1. Gold set (~300)

**Status.** Same labelled gold as DistilBERT v1, scored with the
fine-tuned XLM-R v2 export under
`gs://co-tf-artifacts-dev/nlp/models/xlmr-sent/` (root files only:
`config.json`, `model.safetensors`, tokenizer — not the 10.4 GiB
checkpoint tree). Local CPU inference. DistilBERT v1 artifacts
(`pred.jsonl`, `report.json`) were not overwritten.

| Artifact | Path | Rows |
|---|---|---|
| Stratified candidates | `nlp/eval/artifacts/candidates.jsonl` | 300 |
| Labelled gold | `nlp/eval/artifacts/gold.jsonl` | 300 |
| Predictions (v2) | `nlp/eval/artifacts/pred-xlmr-v2.jsonl` | 300 |
| Evaluate report (v2) | `nlp/eval/artifacts/report-xlmr-v2.json` | — |
| DistilBERT v1 predictions (kept) | `nlp/eval/artifacts/pred.jsonl` | 300 |
| DistilBERT v1 report (kept) | `nlp/eval/artifacts/report.json` | — |
| Local weights (gitignored) | `nlp/eval/artifacts/xlmr-sent/` | from GCS |

**Sampling.** Unchanged from v1: `raw_staging` via `bq` (text length ≥ 8),
then `python -m nlp.eval.sample_gold` (seed 33, n=300, strata
`source`×`language`). Companion SQL:
`nlp/eval/sql/sample_gold.sql`.

**Labels.** `pos` / `neu` / `neg` per `nlp/eval/GUIDELINES.md`
(sentiment toward the game/event). Distribution:

| Label | n | holdout | train |
|---|---|---|---|
| pos | 161 | 36 | 125 |
| neu | 119 | 36 | 83 |
| neg | 20 | 8 | 12 |
| **total** | **300** | **80** | **220** |

Hold-out is ≥ 80 and must not enter `--own-domain` fine-tuning.
The 220 `split=train` rows were oversampled ×10 in the v2 mix, so the
**train slice is in-sample** and scores 1.000. The honest generalisation
number is **holdout**.

**Predictions.** XLM-R v2 export, `MAX_LEN=128`, labels `neg=0` /
`neu=1` / `pos=2`, CPU.

**XLM-R v2 metrics** (`nlp/eval/artifacts/report-xlmr-v2.json`):

| Slice | n | accuracy | macro-F1 | F1 pos / neu / neg |
|---|---|---|---|---|
| overall | 300 | **0.913** | **0.883** | 0.932 / 0.906 / 0.810 |
| holdout | 80 | 0.675 | 0.645 | 0.703 / 0.676 / 0.556 |
| train | 220 | 1.000 | 1.000 | 1.000 / 1.000 / 1.000 |
| EN | 85 | 0.929 | 0.900 | 0.956 / 0.921 / 0.824 |
| non-EN | 215 | 0.907 | 0.875 | 0.923 / 0.901 / 0.800 |

Holdout EN (n=22) accuracy 0.727 / macro-F1 0.724; holdout non-EN
(n=58) 0.655 / 0.548. Gold `language` tags are still `langdetect`
noise — report EN vs non-EN, not every two-letter tag.

**Vs DistilBERT v1** (same gold):

| Slice | v1 acc / macro-F1 | v2 acc / macro-F1 |
|---|---|---|
| overall | 0.533 / 0.472 | **0.913 / 0.883** |
| holdout | 0.525 / 0.498 | **0.675 / 0.645** |
| EN | 0.635 / 0.592 | **0.929 / 0.900** |
| non-EN | 0.493 / 0.425 | **0.907 / 0.875** |

Success bar from the v2 recipe: overall above 0.533 / 0.472; EN not
below ~0.60; non-EN clearly above v1. All three hold. Holdout EN stays
above 0.60 even after stripping the memorised train rows.

```bash
python -m nlp.eval.predict \
  --model-dir nlp/eval/artifacts/xlmr-sent \
  --gold nlp/eval/artifacts/gold.jsonl \
  --output nlp/eval/artifacts/pred-xlmr-v2.jsonl

python -m nlp.eval.evaluate \
  --gold nlp/eval/artifacts/gold.jsonl \
  --pred nlp/eval/artifacts/pred-xlmr-v2.jsonl \
  --output nlp/eval/artifacts/report-xlmr-v2.json
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
XLM-R v2 is **not** deployed on the Endpoint in this eval.

---

## 3. External baselines

Hand-filled CSVs in `nlp/eval/external/` (unchanged from v1):

- Metacritic metascore / user score
- OpenCritic top critic / percent recommended
- Steam Charts (or Steam Spy) player counts

Join on `date_utc` against the window aggregates (mean polarity vs
critic score vs CCU). Steam collector rows can replace the Charts CSV
later; they do not block YouTube gold.

---

## 4. Reproducibility

The gold JSONL, the v2 evaluate report, and the SQL outputs are the
evaluation artifacts. Checkpoint identity for v2: Hugging Face export
at `gs://co-tf-artifacts-dev/nlp/models/xlmr-sent/` after
`load_best_model_at_end` (`macro_f1`). Hybrid eval on the training VM:
accuracy **0.746** / macro-F1 **0.747** at epoch 3
(`global_step=58884`). Local eval copies under
`nlp/eval/artifacts/xlmr-sent/` are gitignored. Workbench was **not**
started for this scoring run.
