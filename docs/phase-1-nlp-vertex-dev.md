# Phase 1 — NLP Vertex ops journal

Operational record for Track C on GCP through 2026-09-12 (CEST): what
ran, where artifacts live, what bills, what is still pending. Commands
live in [`nlp/README.md`](../nlp/README.md) and
[`terraform/modules/vertex_nlp/README.md`](../terraform/modules/vertex_nlp/README.md).
Evaluation numbers for DistilBERT v1:
[`phase-1-nlp-evaluation-distilbert-v1.md`](phase-1-nlp-evaluation-distilbert-v1.md).

Date: 2026-09-12.

---

## Architecture (do not revert)

The 2026-09-05 plan in [`docs/phase-1-plan.md`](phase-1-plan.md) Track C
named XLM-R, weights baked into the Flex Template, and a
`terraform/modules/mlflow` module. **None of that shipped.**

| Decision | What is in the repo |
|---|---|
| Model | English DistilBERT v1 (`distilbert-base-uncased`), 3-class head (`pos`/`neu`/`neg`). Non-EN is a measured limit — see the evaluation doc. |
| Serving | Vertex Endpoint REST from Dataflow (`--nlp_model vertex`). Weights are **not** `COPY`'d into the Flex Template image. |
| Registry | `stub` (default) and `vertex`. Production replay of 4228 rows is still the stub. DistilBERT v1 is **uploaded** to Model Registry; **no Endpoint replica**. |
| Platform | Vertex AI Workbench / Model Registry / Endpoint (thesis Agent Platform). Console labels say Vertex AI; APIs are `aiplatform.googleapis.com` and `notebooks.googleapis.com`. |
| MLflow | File store on the Workbench VM + GCS artifacts. Not Cloud SQL, not Cloud Run, no `terraform/modules/mlflow`. |

Dataflow workers still have no public IP and no PyPI / Hugging Face Hub.
They reach `aiplatform.googleapis.com` over Private Google Access.

---

## Code on `main`

| | SHA | What it added |
|---|---|---|
| [PR #21](https://github.com/MarcinMazuro/pop-vibe-check/pull/21) | `84822cf` | DistilBERT training, Vertex Workbench / Registry / Endpoint Terraform + client, Dataflow `--model vertex`, stub remains default. |
| [PR #22](https://github.com/MarcinMazuro/pop-vibe-check/pull/22) | `b620db0` | CPU-only Workbench, fp16 only on CUDA, MLflow file store + GCS artifacts, IAP SSH docs, idle shutdown omitted by default in Terraform, budget `create_before_destroy`. |

`b620db0` is the merge of #22 into `main`. #21 is `84822cf`.

---

## Cheap GCP (no GPU)

Always-on, not gated:

- Trainer SA `co-ml-trainer-sa-dev` (`iam` module workload `ml-trainer`).
- IAM: trainer `roles/aiplatform.user`; notebooks service agent
  `roles/iam.serviceAccountUser` on that SA; Dataflow worker
  `roles/aiplatform.user` for `Endpoint.predict`; trainer `objectAdmin` on
  the artifacts bucket. Notebooks API enabled in bootstrap.
- Hugging Face caches in `gs://co-tf-artifacts-dev/` (prefix `nlp/` is
  exempt from the 30-day delete):

  | Prefix | Approx. size | Contents |
  |---|---|---|
  | `nlp/datasets/` | ~776 MiB | SST-2, tweet_eval, Sentiment140, GoEmotions |
  | `nlp/models/hf-cache/` | ~769 MiB | DistilBERT Hub layout for offline `from_pretrained` |

Workbench `co-nlp-workbench-dev`: `e2-standard-4`, zone
`europe-central2-b`, no public IP, no Cloud NAT. Training is offline from
GCS (`TRANSFORMERS_OFFLINE=1` and the matching HF flags). Start / stop /
SSH: [`nlp/README.md`](../nlp/README.md) and the vertex_nlp module README.

MLflow:

- Tracking store: local files on the VM (`/home/jupyter/mlruns` by
  default). `gs://` is not a valid MLflow 2.x tracking URI on Workbench.
- Artifact location: `gs://co-tf-artifacts-dev/nlp/mlruns`.
- Experiment: `distilbert-sentiment`.
- UI: start Workbench, then `mlflow ui --backend-store-uri /home/jupyter/mlruns`
  (or inspect `nlp/mlruns-tracking/` + `nlp/mlruns/<run_id>/` on GCS).

---

## Budget

GCP Billing budget display name `co dev monthly budget`: **50 PLN**,
thresholds 50 / 90 / 100 / 120%. **Alert only — not a hard cap.** Spend
continues after 100%.

Notification emails (GCP verification required before delivery):

- `polishek123@gmail.com`
- `mazuromarcin@gmail.com`

**Operational note (2026-09-10).** The budget was re-hung on billing
account `0160EC-265597-269268` (the account the project is linked to). It
previously sat on `01F77F-…` and reported $0 spend. Terraform now uses
`create_before_destroy` on the budget so a billing-account replace cannot
leave the env with no budget. The Terraform runner SA may still lack
`roles/billing.costsManager` on `0160EC-…`; if a later apply cannot
manage the budget, grant that role on the new account (or apply the
budget with a human identity).

---

## CPU-only (train + serve)

Training and Endpoint serving stay on CPU: Workbench `e2-standard-4`,
zone `europe-central2-b`, instance `co-nlp-workbench-dev`; deploy with
`n1-standard-8` and no accelerator (`nlp/endpoint/register.py`). Do not
attach guest accelerators on this billing account.

---

## Idle shutdown (2026-09-10)

Terraform's then-default `idle-timeout-seconds=10800` (3 h) stopped the
VM around **16:11 CEST**, after a start around **13:09**. The Notebooks
service agent called `compute.instances.stop`. An SSH training process
**does not** reset Jupyter idle; the timer is independent of `nohup`.

Clearing the key with `gcloud … --metadata=idle-timeout-seconds=`
(empty value) removes it from instance metadata but **does not restart**
`google-wi-idle-shutdown.service`. The timer started at boot still
fired.

Fix that actually stuck, on the live VM:

1. `systemctl mask google-wi-idle-shutdown.service`
2. Leave `idle-timeout-seconds` **absent** from metadata

Terraform `0` is not a GCP off switch. The API rejects the value `0`
(valid enabled range is 600–86400). PR #22 omits the key when the
variable is `0`. That is the disable path.

Idle shutdown is now **off** in module defaults. After this training run
finishes, **stop the VM by hand** — nothing will auto-stop it.

---

## Training (complete 12 Sep 2026)

The 10 Sep restart ran to completion on CPU (`nohup`; ~44.5 h wall,
`global_step=75090`, finished ~16:27 CEST). Best checkpoint is epoch 2
(**DistilBERT v1**).

| | |
|---|---|
| Examples | ~222k |
| Batch | 8 |
| Epochs | 3 |
| Steps | 75090 |
| CUDA | false |
| Best | epoch 2 / `checkpoint-50060` |
| Best acc (hybrid holdout) | 0.802 |
| Best metric (macro-F1) | 0.786 |
| Epoch 3 acc | 0.801 (worse; not selected) |

Weights and checkpoints are on GCS (`gsutil -m cp -r` 2026-09-12):

| Prefix | Size | Contents |
|---|---|---|
| `nlp/models/distilbert-sent/` | 2.50 GiB | `model.safetensors` (256 MiB), tokenizer, `train.log`, `checkpoints/checkpoint-25030\|50060\|75090` |
| `nlp/mlruns/286827588c4749588d09e40bb332b8e7/` | already present | MLflow artifacts from the run |
| `nlp/mlruns-tracking/` | 1.8 KiB | local file-store copy (`metrics`/`params`/`tags`) |

`co-nlp-workbench-dev` was stopped by hand after the copy
(`gcloud workbench instances stop …`). State is **STOPPED** (not
deleted). Boot + data disks remain. Idle shutdown is still off; do not
`enable_nlp_workbench=false` (that destroys the VM).

---

## Model Registry (upload only, 12 Sep 2026)

Upload via `nlp/endpoint/register.py` — **no Endpoint deploy**, so no
node-hour serving charge.

| | |
|---|---|
| Resource | `projects/891032629527/locations/europe-central2/models/6682862459948105728` |
| displayName | `distilbert-sent` |
| Version | `1` |
| Artifact URI | `gs://co-tf-artifacts-dev/nlp/models/distilbert-sent` |
| Container | `europe-docker.pkg.dev/vertex-ai/prediction/huggingface-pytorch-inference-cpu.2-3:latest` |

TorchServe `pytorch-cpu` rejected the HF directory layout (expects
`.mar`). Endpoint count in `europe-central2` after upload: **0**.

---

## Pending — serve-replay

CPU Endpoint deploy (`n1-standard-8`, no accelerator) → Dataflow
`--model vertex` → undeploy after drain. Do not treat
`events.model_version` as `vertex/…` until that lands. Production
classification remains the stub on 4228 rows.

---

## Related

| Doc | Role |
|---|---|
| [`nlp/README.md`](../nlp/README.md) | Train, register, deploy, launch |
| [`terraform/modules/vertex_nlp/README.md`](../terraform/modules/vertex_nlp/README.md) | Gates, IAM, IAP SSH, cost runbook |
| [`phase-1-nlp-evaluation-distilbert-v1.md`](phase-1-nlp-evaluation-distilbert-v1.md) | DistilBERT v1 gold metrics |
| [`phase-1-dataflow.md`](phase-1-dataflow.md) | Stub replay that is still in `events` |
| [`phase-1-plan.md`](phase-1-plan.md) | Track C (C1–C3 superseded; pointer here) |
