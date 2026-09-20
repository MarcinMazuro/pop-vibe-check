# Phase 1 — NLP multilingual v2.1 continued fine-tune

Recipe for a short second fine-tune of the multilingual XLM-R sentiment
model. This stage starts from the evaluated v2 export; it does not retrain
from `xlm-roberta-base`. The v2 baseline and its measured results are in
[`phase-1-nlp-evaluation-xlmr-v2.md`](phase-1-nlp-evaluation-xlmr-v2.md).

Date: 2026-09-20.

## Goal and success bar

Start from:

`gs://co-tf-artifacts-dev/nlp/models/xlmr-sent/`

This is the v2 export (tokenizer and model files). The continued model is
written separately as `xlmr-sent-v2.1`; the v2 artifact is never overwritten.

Success is decided on `gold_v3.jsonl`, using the same rows for v2 and v2.1:

- v2.1 has higher holdout macro-F1 than v2;
- v2.1 has higher holdout `neg` F1;
- EN holdout performance does not decrease;
- the original 80 holdout rows remain in the expanded holdout.

Do not invent or fill in metrics before the training and evaluation commands
produce them.

## Stage 1 — local candidate preparation and review

The prelabel flow is local and uses no Gemini API or other LLM API. First
obtain `candidates_v3.jsonl` through the approved data export, then run:

```bash
python -m nlp.eval.prelabel_chunks split \
  --input nlp/eval/artifacts/candidates_v3.jsonl

# The Cursor agent labels each chunk on disk with label_llm and
# llm_confidence, following nlp/eval/GUIDELINES.md.
python -m nlp.eval.prelabel_chunks merge
python -m nlp.eval.prelabel_chunks select
```

The `select` command marks `review_required` for all negative prelabels,
low-confidence rows, and rows allocated to the future dev or holdout sets.
The user reviews those rows and fills their human `label` values. Then merge
the reviewed rows with the existing gold:

```bash
python -m nlp.eval.merge_gold \
  --gold nlp/eval/artifacts/gold.jsonl \
  --review nlp/eval/artifacts/gold_v3_review.jsonl \
  --output nlp/eval/artifacts/gold_v3.jsonl
```

`merge_gold` keeps the old holdout and expands the holdout to the configured
target (at least 200 rows by default), assigns a stratified dev split, and
writes the agreement report. Rows that require review are not accepted until
the human `label` is filled.

The candidate export from BigQuery requires owner GCP consent. Do not run a
BigQuery export without that consent.

## Stage 2 — continued fine-tune on Workbench

The Workbench run starts from the v2 export copied locally from
`gs://co-tf-artifacts-dev/nlp/models/xlmr-sent/`. It uses the v2 public mix as
replay data and the reviewed `gold_v3.jsonl` domain rows:

```bash
python -m nlp.training.train \
  --init-from /home/jupyter/models/xlmr-sent \
  --cache-dir /home/jupyter/hf-datasets \
  --model-cache-dir /home/jupyter/hf-cache \
  --own-domain /home/jupyter/gold/gold_v3.jsonl \
  --dev-from-gold /home/jupyter/gold/gold_v3.jsonl \
  --replay-n 5000 \
  --lr 1e-5 \
  --epochs 3 \
  --batch-size 8 \
  --own-domain-factor 2 \
  --warmup-ratio 0.1 \
  --weight-decay 0.01 \
  --early-stopping-patience 2 \
  --output-dir /home/jupyter/models/xlmr-sent-v2.1
```

`--dev-from-gold` evaluates on rows with `split == dev`; holdout rows are
never used for fine-tuning. Reduce `--batch-size` to 4 only if the selected
CPU machine runs out of memory. Stop the Workbench instance after the run.

Workbench access and training require owner GCP consent. This recipe does not
deploy a Vertex Endpoint.

## Evaluation and decision

Copy the v2 export and the v2.1 output to local directories, then score both
on the same expanded gold file:

```bash
python -m nlp.eval.predict \
  --model-dir nlp/eval/artifacts/xlmr-sent \
  --gold nlp/eval/artifacts/gold_v3.jsonl \
  --output nlp/eval/artifacts/pred-xlmr-v2-goldv3.jsonl

python -m nlp.eval.evaluate \
  --gold nlp/eval/artifacts/gold_v3.jsonl \
  --pred nlp/eval/artifacts/pred-xlmr-v2-goldv3.jsonl \
  --output nlp/eval/artifacts/report-xlmr-v2-goldv3.json

python -m nlp.eval.predict \
  --model-dir nlp/eval/artifacts/xlmr-sent-v2.1 \
  --gold nlp/eval/artifacts/gold_v3.jsonl \
  --output nlp/eval/artifacts/pred-xlmr-v2.1-goldv3.jsonl

python -m nlp.eval.evaluate \
  --gold nlp/eval/artifacts/gold_v3.jsonl \
  --pred nlp/eval/artifacts/pred-xlmr-v2.1-goldv3.jsonl \
  --output nlp/eval/artifacts/report-xlmr-v2.1-goldv3.json
```

Fill this table from the two evaluation reports. The decision uses the
holdout slice; EN means the EN holdout slice.

| Model | Holdout n | Holdout macro-F1 | Holdout neg F1 | EN holdout macro-F1 | Decision |
|---|---:|---:|---:|---:|---|
| v2 |  |  |  |  | baseline |
| v2.1 |  |  |  |  |  |

If any success condition fails, keep v2 as the selected artifact and record
the result rather than promoting v2.1.

## Artifact upload

Only after the evaluation decision, upload the new model under a new prefix:

```bash
gsutil -m cp -r /home/jupyter/models/xlmr-sent-v2.1 \
  gs://co-tf-artifacts-dev/nlp/models/xlmr-sent-v2.1/
```

The GCS upload requires owner GCP consent. It must not overwrite
`gs://co-tf-artifacts-dev/nlp/models/xlmr-sent/`. This recipe has no Endpoint
deploy step; any later registration or deployment is a separate, explicitly
approved operation.
