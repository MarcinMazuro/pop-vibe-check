# nlp — sentiment models for the Dataflow pipeline

The Beam pipeline loads a classifier by name (`--nlp_model`) and never
imports a concrete implementation. Today two names are registered:

| Name | Class | When to use |
|---|---|---|
| `stub` | `nlp.stub.classifier.StubClassifier` | Default. Deterministic, no GCP. First e2e replay. |
| `vertex` | `nlp.endpoint.classifier.VertexEndpointClassifier` | DistilBERT on a Vertex Endpoint. Needs env + a live replica. |

Weights are **not** baked into the Flex Template image. Dataflow workers
reach `aiplatform.googleapis.com` over Private Google Access; they still
cannot reach PyPI or Hugging Face Hub.

## Layout

| Path | Purpose |
|---|---|
| `base.py` | `Sentiment` / `SentimentClassifier` contract (`pos`/`neu`/`neg`) |
| `registry.py` | Name → factory. Add models here; leave the pipeline alone |
| `stub/` | Rule-based placeholder |
| `endpoint/` | Vertex predict client + Model Registry upload/deploy/undeploy CLI |
| `training/` | Hybrid corpus loaders + DistilBERT `train.py` (Workbench) |
| `tracking/` | MLflow → GCS (`mlruns/`). Not the Dataflow factory |
| `eval/` | Gold sample, guidelines, metrics, time-window SQL, external CSVs |
| `notebooks/` | Workbench walkthrough |

## Training on Vertex AI Workbench (T4)

Infra is gated **off**. A routine `terraform apply` does not create the
GPU VM. For a training session, from `terraform/envs/dev`:

```bash
terraform apply \
  -var="enable_nlp_workbench=true" \
  -var='nlp_workbench_owners=["you@example.com"]' \
  -var="nlp_workbench_desired_state=ACTIVE"
```

Zone is `europe-central2-b` (T4 is not in `-a`). The instance runs as
`co-ml-trainer-sa-dev`, on `co-vpc-dev` / `co-subnet-dev`, no public IP.

In Jupyter:

```bash
git clone <this repo> && cd pop-vibe-check
pip install -r nlp/training/requirements.txt

# Dataset cache — do this once, then rsync on later sessions:
#   gsutil -m rsync -r /home/jupyter/hf-datasets gs://co-tf-artifacts-dev/nlp/datasets/
gsutil -m rsync -r gs://co-tf-artifacts-dev/nlp/datasets/ /home/jupyter/hf-datasets

python -m nlp.training.train \
  --cache-dir /home/jupyter/hf-datasets \
  --output-dir /home/jupyter/models/distilbert-sent \
  --own-domain /home/jupyter/gold/own_domain.jsonl   # optional
```

Or open `nlp/notebooks/finetune_distilbert.ipynb`.

**Stop the GPU when the run finishes.** Idle shutdown (3 h) is a
backstop, not a plan:

```bash
gcloud workbench instances stop co-nlp-workbench-dev \
  --location=europe-central2-b
# or: terraform apply -var="enable_nlp_workbench=true" -var="nlp_workbench_desired_state=STOPPED"
# or: terraform apply   # gates default false → destroys the instance
```

### Hybrid corpus

- **SST-2** (`glue`/`sst2`, ~67k) — movie reviews, `pos`/`neg` only.
- **Twitter ~100k** — `tweet_eval` sentiment (3-class) plus a seeded
  Sentiment140 sample to fill the rest.
- **Own domain** — labelled YouTube gold (`nlp/eval/GUIDELINES.md`). The
  Reddit collector has no credentials; GoEmotions (public Reddit
  comments) is the open-access substitute. Loaded unless
  `--skip-goemotions`.

Model: `distilbert-base-uncased`, 3-class head, `MAX_LEN=128`.
English-only base; non-EN rows are measured in eval, not promised.

### MLflow

`nlp/tracking/mlflow_utils.py` logs lr / epochs / batch, accuracy,
macro-F1, per-class P/R/F1, and the weight directory to
`gs://co-tf-artifacts-dev/nlp/mlruns`. That GCS prefix is exempt from
the artifacts-bucket 30-day delete.

## Model Registry and Endpoint

Terraform may create an **empty** Endpoint (`enable_nlp_endpoint=true`).
It does not upload versions or deploy replicas — those would put GPU
serving in `terraform apply`.

```bash
gsutil -m cp -r /home/jupyter/models/distilbert-sent \
  gs://co-tf-artifacts-dev/nlp/models/distilbert-sent/

python -m nlp.endpoint.register upload \
  --project pop-vibe-check \
  --model-dir gs://co-tf-artifacts-dev/nlp/models/distilbert-sent \
  --display-name distilbert-sent

terraform apply -var="enable_nlp_endpoint=true"

python -m nlp.endpoint.register deploy \
  --project pop-vibe-check \
  --model projects/.../models/... \
  --endpoint "$(terraform -chdir=terraform/envs/dev output -raw vertex_endpoint_id)" \
  --machine-type n1-standard-4 \
  --accelerator NVIDIA_TESLA_T4
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

An empty Endpoint does not bill for GPU. A deployed T4 replica does,
until undeployed.

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

See [docs/nlp-evaluation.md](../docs/nlp-evaluation.md).

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
