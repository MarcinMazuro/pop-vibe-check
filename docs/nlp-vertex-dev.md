# NLP — DistilBERT on Vertex (dev status)

What landed for Track C through 2026-09-10 (evening CEST), and what is
still running. Commands live in [`nlp/README.md`](../nlp/README.md) and
[`terraform/modules/vertex_nlp/README.md`](../terraform/modules/vertex_nlp/README.md);
this file is the operational record.

Date: 2026-09-10.

---

## Architecture (do not revert)

The 2026-09-05 plan in [`docs/phase-1-plan.md`](phase-1-plan.md) Track C
named XLM-R, weights baked into the Flex Template, and a
`terraform/modules/mlflow` module. **None of that shipped.**

| Decision | What is in the repo |
|---|---|
| Model | English DistilBERT (`distilbert-base-uncased`), 3-class head (`pos`/`neu`/`neg`). Non-EN is a measured limit, not a quality target — [`docs/nlp-evaluation.md`](nlp-evaluation.md). |
| Serving | Vertex Endpoint REST from Dataflow (`--nlp_model vertex`). Weights are **not** `COPY`'d into the Flex Template image. |
| Registry | `stub` (default) and `vertex`. The production replay of 4228 rows is still the stub. |
| Platform | Vertex AI Workbench / Model Registry / Endpoint (thesis Agent Platform). Console labels say Vertex AI; APIs are `aiplatform.googleapis.com` and `notebooks.googleapis.com`. |
| MLflow | File store on the Workbench VM + GCS artifacts. Not Cloud SQL, not Cloud Run, no `terraform/modules/mlflow`. |

Dataflow workers still have no public IP and no PyPI / Hugging Face Hub.
They reach `aiplatform.googleapis.com` over Private Google Access.

---

## Code on `main`

| | SHA | What it added |
|---|---|---|
| [PR #21](https://github.com/MarcinMazuro/pop-vibe-check/pull/21) | `84822cf` | DistilBERT training, Vertex Workbench / Registry / Endpoint Terraform + client, Dataflow `--model vertex`, stub remains default. |
| [PR #22](https://github.com/MarcinMazuro/pop-vibe-check/pull/22) | `b620db0` | CPU-only Workbench (no T4), fp16 only on CUDA, MLflow file store + GCS artifacts, IAP SSH docs, idle shutdown omitted by default in Terraform, budget `create_before_destroy`. |

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

## T4 / free tier

Creating Workbench with a T4 failed:

> free tier where non-TPU accelerators are not available

Training therefore runs on CPU: `e2-standard-4`, `europe-central2-b`,
instance `co-nlp-workbench-dev`. Do not attach an accelerator on this
billing account.

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

## Training (evening 10 Sep 2026)

After the idle stop, the run restarted **from scratch** (checkpoint
directory empty). Process is `nohup`; log
`/home/jupyter/models/distilbert-sent/train.log`.

| | |
|---|---|
| Examples | ~222k |
| Batch | 8 |
| Epochs | 3 |
| Steps | ~75k |
| ETA | ~41 h |
| CUDA | false |

When it finishes (not done as of this writing):

1. Manual STOP of `co-nlp-workbench-dev` (idle will not do it).
2. `gsutil cp` weights to `gs://co-tf-artifacts-dev/nlp/models/distilbert-sent/`.
3. Registry upload / Endpoint deploy / Dataflow `--model vertex` — see
   [`nlp/README.md`](../nlp/README.md).

**Pending — serve-replay.** Deploying an Endpoint replica with a T4, and
the DistilBERT Dataflow replay that would use it, are **blocked on free
tier** (same accelerator restriction as Workbench). Do not treat
`events.model_version` as `vertex/…` until that unblocks. Production
classification remains the stub on 4228 rows.

---

## Related

| Doc | Role |
|---|---|
| [`nlp/README.md`](../nlp/README.md) | Train, register, deploy, launch |
| [`terraform/modules/vertex_nlp/README.md`](../terraform/modules/vertex_nlp/README.md) | Gates, IAM, IAP SSH, cost runbook |
| [`docs/nlp-evaluation.md`](nlp-evaluation.md) | Gold set, windows, baselines |
| [`docs/phase-1-dataflow.md`](phase-1-dataflow.md) | Stub replay that is still in `events` |
| [`docs/phase-1-plan.md`](phase-1-plan.md) | Track C (C1–C3 superseded; pointer here) |
