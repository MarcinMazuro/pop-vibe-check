# Phase 1 — NLP multilingual v2 (XLM-RoBERTa)

Recipe for replacing English DistilBERT v1 with `xlm-roberta-base`.
Training has **not** been run yet. DistilBERT v1 numbers stay in
[`phase-1-nlp-evaluation-distilbert-v1.md`](phase-1-nlp-evaluation-distilbert-v1.md)
and the Vertex ops journal
[`phase-1-nlp-vertex-dev.md`](phase-1-nlp-vertex-dev.md).

Date: 2026-09-15.

---

## Why v2

DistilBERT v1 (`distilbert-base-uncased`) scored **0.802 acc / 0.786
macro-F1** on the English hybrid holdout and **0.533 / 0.472** on the
YouTube gold set (EN-only ≈ 0.635). Three problems, not one:

1. **English encoder** on comments that are not English (Steam mix is
   ~49% EN plus ZH/RU/FR/KO).
2. **Domain gap** — SST-2 movies and Sentiment140 are a poor match for
   game comments; 220 gold train rows were drowned in 222k public rows.
3. **Class imbalance** on gold (`neg` = 20/300); neu often predicted as
   pos.

XLM-R base (~278M, 100 languages) is the original Track C model. It is
heavier than DistilmBERT but fits a CPU Workbench **`n2-standard-16`**
(64 GB) at batch 8. GPU stays off.

---

## Model

| | |
|---|---|
| Hub id | `xlm-roberta-base` |
| Task | 3-class `neg` / `neu` / `pos` (same `LABEL2ID` as v1) |
| `MAX_LEN` | 128 |
| Artifact | `xlmr-sent` |
| MLflow | experiment `xlmr-sentiment` |
| Override | `--model-name distilbert-base-uncased` still reproduces v1 |

Serving is unchanged: Hugging Face CPU prediction container on
`n1-standard-8`, Dataflow `--nlp_model vertex`.

---

## Languages

**Trained for sentiment:** `en, zh, ru, fr, ko` (Steam-centric caps) plus
`de, es, ja` and the eight CardiffNLP tweet languages (ar/en/fr/de/hi/it/pt/es).

**Tokenizer / pretraining:** ~100 languages, including Polish. There is
**no Polish labelled mix** in clapAI; PL quality is transfer-only until
gold or PolEmo is added.

Inference does not filter by language. Gold `language` slices from
`langdetect` remain noisy on short comments — report EN vs non-EN, not
every two-letter tag.

---

## Corpus (~150–180k)

Default mix in `nlp.training.loaders.load_v2_corpus` (seed 33):

| Source | n (target) | ~% | Notes |
|---|---|---|---|
| clapAI MultiLingualSentiment | 18k × {en,zh,ru,fr,ko} + 6k × {de,es,ja} | ~62% | 3-class; reservoir; drop texts > 512 chars |
| tweet_eval sentiment | 25k (down from ~60k) | ~15% | English social 3-class |
| CardiffNLP tweet_sentiment_multilingual | ~24k (all configs) | ~14% | 8 languages, labels 0/1/2 |
| GoEmotions | 15k | ~9% | Reddit substitute |
| YouTube gold `split=train` | 220 × 10 | ~1% | `split=holdout` is skipped |

**Off by default:** SST-2, Sentiment140 (`--include-sst2`,
`--include-sentiment140`). Those drove the v1 domain gap.

Training extras vs v1: inverse-frequency class weights, stratified 90/10
split, DataLoader workers, `torch.set_num_threads`. Best checkpoint by
`macro_f1` (epoch 3 lost on v1).

---

## Workbench (CPU, no GPU)

Stay in `europe-central2-b`. Do **not** change the Terraform default
(`e2-standard-4`). For this run only:

```bash
terraform apply \
  -var="enable_nlp_workbench=true" \
  -var="nlp_workbench_desired_state=ACTIVE" \
  -var="nlp_workbench_machine_type=n2-standard-16" \
  -var='nlp_workbench_owners=["you@example.com"]'
```

Batch default is 8; drop to 4 on OOM. Fallback machine:
`n2-standard-8` (32 GB) if `n2-standard-16` is missing in the zone.
Wall-clock estimate 25–45 h. Stop the VM by hand when finished — idle
shutdown is off.

Do not run these commands until the project owner confirms GCP.

After the first Hub download, rsync caches back to
`gs://co-tf-artifacts-dev/nlp/datasets/` and
`gs://co-tf-artifacts-dev/nlp/models/hf-cache/` so later sessions stay
offline (`TRANSFORMERS_OFFLINE=1`).

---

## Eval bar (same gold)

Reuse `nlp/eval/artifacts/gold.jsonl` (holdout 80 never in `--own-domain`).

| Slice | v1 | v2 success |
|---|---|---|
| overall acc / macro-F1 | 0.533 / 0.472 | higher than v1 |
| EN acc | ≈ 0.635 | do not collapse below ~0.60 |
| non-EN | measured limit | clearly above v1 |

Hybrid 0.80 is **not** the thesis target — that number was in-distribution
English public data.

---

## Code

| Path | Change |
|---|---|
| `nlp/training/labels.py` | `MODEL_NAME`, clapAI map, class weights |
| `nlp/training/loaders.py` | v2 mix |
| `nlp/training/train.py` | CLI, stratified split, weighted CE |
| `nlp/endpoint/register.py` | defaults `xlmr-sent` |
| `nlp/README.md` | runbook |

`--model-name` keeps DistilBERT v1 reproducible without reverting the mix
flags (`--include-sst2 --include-sentiment140` plus skip clapAI / tweet-ml).
