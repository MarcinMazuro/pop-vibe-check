# nlp — sentiment models for the Dataflow pipeline

The Beam pipeline loads a classifier by name (`--nlp_model`) and never
imports a concrete implementation. Today two **serving** names are
registered in `nlp/registry.py`:

| Name | Class | When to use |
|---|---|---|
| `stub` | `nlp.stub.classifier.StubClassifier` | Default. Deterministic, no GCP. First e2e replay. |
| `vertex` | `nlp.endpoint.classifier.VertexEndpointClassifier` | Fine-tuned checkpoint on a Vertex Endpoint. Needs env + a live replica. |

Trained Hugging Face exports (ids, GCS URIs, gold-holdout metrics) live
in `nlp/catalog.py`. That catalog does **not** change `--nlp_model`.
XLM-R v2.1 is the selected artifact after the gold_v3 holdout comparison.
v2 and v2.1 are in Vertex Model Registry (`europe-central2`); v2.1 is
deployed on `co-nlp-endpoint-dev`.

Weights are **not** baked into the Flex Template image. Dataflow workers
reach `aiplatform.googleapis.com` over Private Google Access; they still
cannot reach PyPI or Hugging Face Hub.

**Current status (2026-09-21).** DistilBERT v1 train complete (best epoch 2,
hybrid acc 0.802, macro-F1 0.786) at
`gs://co-tf-artifacts-dev/nlp/models/distilbert-sent/`. XLM-R v2.1
continued fine-tune finished 2026-09-20 (gold_v3 holdout n=200: acc
0.630 / macro-F1 0.600 vs v2 0.590 / 0.568) at
`gs://co-tf-artifacts-dev/nlp/models/xlmr-sent-v2.1/`; v2 is kept at
`gs://co-tf-artifacts-dev/nlp/models/xlmr-sent/`. Catalog:
[`nlp/catalog.py`](catalog.py). Eval:
[docs/phase-1-nlp-evaluation-xlmr-v2.md](../docs/phase-1-nlp-evaluation-xlmr-v2.md),
[docs/phase-1-nlp-xlmr-v2.1-continued.md](../docs/phase-1-nlp-xlmr-v2.1-continued.md).
Serve-replay is still pending. DistilBERT ops journal:
[docs/phase-1-nlp-vertex-dev.md](../docs/phase-1-nlp-vertex-dev.md).

## Layout

| Path | Purpose |
|---|---|
| `base.py` | `Sentiment` / `SentimentClassifier` contract (`pos`/`neu`/`neg`) |
| `registry.py` | Serving name → factory (`stub` / `vertex`). Leave the pipeline alone |
| `catalog.py` | Trained artifact catalog (GCS URI, gold-holdout metrics, selected) |
| `stub/` | Rule-based placeholder |
| `endpoint/` | Vertex predict client + Model Registry upload/deploy/undeploy CLI |
| `training/` | Hybrid corpus loaders + XLM-RoBERTa `train.py` (Workbench) |
| `tracking/` | MLflow → GCS (`mlruns/`). Not the Dataflow factory |
| `eval/` | Gold sample, guidelines, metrics, time-window SQL, external CSVs |
| `notebooks/` | Workbench walkthrough |

## Training on Vertex AI Workbench (CPU by default)

Infra is gated **off**. A routine `terraform apply` does not create the
VM. Default machine is `e2-standard-4` (CPU-only). For the XLM-R v2
training session use **`n2-standard-16`** (or `n2-standard-8` if 16 is
unavailable), from `terraform/envs/dev`:

```bash
terraform apply \
  -var="enable_nlp_workbench=true" \
  -var='nlp_workbench_owners=["you@example.com"]' \
  -var="nlp_workbench_desired_state=ACTIVE" \
  -var="nlp_workbench_machine_type=n2-standard-16"
```

Zone is `europe-central2-b`. The instance runs as `co-ml-trainer-sa-dev`,
on `co-vpc-dev` / `co-subnet-dev`, no public IP. SSH over IAP is documented
in `terraform/modules/vertex_nlp/README.md`.

On the VM (user `jupyter`):

```bash
git clone <this repo> && cd pop-vibe-check
python -m venv ~/hf-venv && source ~/hf-venv/bin/activate
pip install -r nlp/training/requirements.txt

gsutil -m rsync -r gs://co-tf-artifacts-dev/nlp/datasets/ /home/jupyter/hf-datasets
gsutil -m rsync -r gs://co-tf-artifacts-dev/nlp/models/hf-cache/ /home/jupyter/hf-cache

export HF_HUB_CACHE=/home/jupyter/hf-cache
export HF_HOME=/home/jupyter/hf-home
# First v2 session: leave Hub online (clapAI + xlm-roberta-base are not in the
# DistilBERT v1 cache). After rsyncing new caches to GCS:
# export TRANSFORMERS_OFFLINE=1 HF_HUB_OFFLINE=1 HF_DATASETS_OFFLINE=1

python -m nlp.training.train \
  --cache-dir /home/jupyter/hf-datasets \
  --model-cache-dir /home/jupyter/hf-cache \
  --output-dir /home/jupyter/models/xlmr-sent \
  --batch-size 8 \
  --own-domain /home/jupyter/gold/gold.jsonl
```

First session will hit the Hub (clapAI + XLM-R + CardiffNLP). After that,
rsync caches back to GCS and set the `*_OFFLINE=1` flags. `train.py` turns
fp16 off on CPU. Drop `--batch-size` to 4 if the VM OOMs.

Holdout rows (`split=holdout`) in the gold JSONL are skipped automatically.

Or open `nlp/notebooks/finetune_distilbert.ipynb` (updated for XLM-R).

**Stop the instance when the run finishes.** Idle shutdown is off by
default and will not stop this run:

```bash
gcloud workbench instances stop co-nlp-workbench-dev \
  --location=europe-central2-b
# or: terraform apply -var="enable_nlp_workbench=true" -var="nlp_workbench_desired_state=STOPPED"
# or: terraform apply   # gates default false → destroys the instance
```

### Stage 2 continued fine-tune (v2 → v2.1)

Use the reviewed `gold_v3.jsonl` and start from the existing v2 export. The
full local prelabel, human review, evaluation, and consent gates are in
[docs/phase-1-nlp-xlmr-v2.1-continued.md](../docs/phase-1-nlp-xlmr-v2.1-continued.md).
The Workbench training command is:

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

This stage does not start from `xlm-roberta-base`, does not overwrite the v2
artifact, and does not deploy an Endpoint. Workbench access and the later GCS
upload each require owner GCP consent.

### Hybrid corpus (v2 default)

See [docs/phase-1-nlp-multilingual-v2.md](../docs/phase-1-nlp-multilingual-v2.md)
for the table. Short version:

- **clapAI MultiLingualSentiment** — stratified subsample, Steam langs
  en/zh/ru/fr/ko plus de/es/ja.
- **tweet_eval** — English 3-class, downsampled to 25k.
- **CardiffNLP tweet_sentiment_multilingual** — 8 languages, all configs.
- **GoEmotions** — Reddit substitute, downsampled to 15k.
- **Own domain** — YouTube gold train rows, oversampled ×10. Holdout never
  enters training.

SST-2 and Sentiment140 are **off** (`--include-sst2` /
`--include-sentiment140` restore the v1 leftovers).

Model: `xlm-roberta-base`, 3-class head, `MAX_LEN=128`.

### MLflow

`nlp/tracking/mlflow_utils.py` logs lr / epochs / batch, accuracy,
macro-F1, per-class P/R/F1, and the weight directory to
`gs://co-tf-artifacts-dev/nlp/mlruns`. That GCS prefix is exempt from
the artifacts-bucket 30-day delete.

## Model Registry and Endpoint

Terraform may create an **empty** Endpoint (`enable_nlp_endpoint=true`).
It does not upload versions or deploy replicas — those would put a
billing replica into `terraform apply`.

```bash
gsutil -m cp -r /home/jupyter/models/xlmr-sent \
  gs://co-tf-artifacts-dev/nlp/models/xlmr-sent/

python -m nlp.endpoint.register upload \
  --project pop-vibe-check \
  --model-dir gs://co-tf-artifacts-dev/nlp/models/xlmr-sent \
  --display-name xlmr-sent

terraform apply -var="enable_nlp_endpoint=true"

python -m nlp.endpoint.register deploy \
  --project pop-vibe-check \
  --model projects/.../models/... \
  --endpoint "$(terraform -chdir=terraform/envs/dev output -raw vertex_endpoint_id)" \
  --machine-type n1-standard-8
```

Then replay:

```bash
dataflow/launch.sh --model vertex
# VERTEX_ENDPOINT_ID / VERTEX_PROJECT / VERTEX_LOCATION come from terraform output
```

After drain:

```bash
python -m nlp.endpoint.register undeploy --endpoint "$VERTEX_ENDPOINT_ID"
gcloud workbench instances stop co-nlp-workbench-dev --location=europe-central2-b
```

An empty Endpoint does not bill for a replica. A deployed CPU replica
does, until undeployed.

## Dataflow client

`VertexEndpointClassifier` reads:

| Env | Meaning |
|---|---|
| `VERTEX_ENDPOINT_ID` | Endpoint resource name (terraform output `vertex_endpoint_id`) |
| `VERTEX_PROJECT` | GCP project |
| `VERTEX_LOCATION` | `europe-central2` |

`classify_batch` → one `Endpoint.predict`. Retries 429/5xx (tenacity).
After retries it **raises** so Beam retries the bundle — it does not
invent `neu`.

## Evaluation

See [docs/phase-1-nlp-evaluation-xlmr-v2.md](../docs/phase-1-nlp-evaluation-xlmr-v2.md)
(v2 results), [docs/phase-1-nlp-multilingual-v2.md](../docs/phase-1-nlp-multilingual-v2.md)
(v2 recipe), and
[docs/phase-1-nlp-xlmr-v2.1-continued.md](../docs/phase-1-nlp-xlmr-v2.1-continued.md)
(continued v2.1 recipe).
[docs/phase-1-nlp-evaluation-distilbert-v1.md](../docs/phase-1-nlp-evaluation-distilbert-v1.md)
(v1 gold numbers).

```bash
python -m nlp.eval.sample_gold --input raw.jsonl --output gold.jsonl --n 300
python -m nlp.eval.evaluate --gold gold.jsonl --pred pred.jsonl
```

## Tests

```bash
pytest nlp/tests
```

No Hugging Face downloads, no GCP. Loaders' label maps and the Vertex
client (mocked predict) are what CI covers.
