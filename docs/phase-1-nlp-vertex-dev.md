# Phase 1 — NLP Vertex ops journal

Operational record for Track C on GCP through 2026-09-21 (CEST): what
ran, where artifacts live, what bills, what is still pending. Commands
live in [`nlp/README.md`](../nlp/README.md) and
[`terraform/modules/vertex_nlp/README.md`](../terraform/modules/vertex_nlp/README.md).
Evaluation numbers for DistilBERT v1:
[`phase-1-nlp-evaluation-distilbert-v1.md`](phase-1-nlp-evaluation-distilbert-v1.md).

Date: 2026-09-12, updated 2026-10-11 against the live project. XLM-R
recipes and results:
[`phase-1-nlp-multilingual-v2.md`](phase-1-nlp-multilingual-v2.md) (v2),
[`phase-1-nlp-evaluation-xlmr-v2.md`](phase-1-nlp-evaluation-xlmr-v2.md)
(v2 eval),
[`phase-1-nlp-xlmr-v2.1-continued.md`](phase-1-nlp-xlmr-v2.1-continued.md)
(v2.1).

> **State on 2026-10-11.** `events` holds **12,254 rows, all classified
> by XLM-R v2.1** through the Vertex Endpoint (replay of 2026-09-21). The
> stub no longer has a row in `events`. The Endpoint has since been
> deleted, so nothing serves and nothing bills. See
> [Serve-replay](#serve-replay-xlm-r-v21-21-sep-2026).

---

## Architecture (do not revert)

The 2026-09-05 plan in [`docs/phase-1-plan.md`](phase-1-plan.md) Track C
named XLM-R, weights baked into the Flex Template, and a
`terraform/modules/mlflow` module. **None of that shipped.**

| Decision | What is in the repo |
|---|---|
| Model | Multilingual **XLM-R v2.1** (`xlm-roberta-base` → v2 → continued fine-tune), 3-class head (`pos`/`neu`/`neg`). English DistilBERT v1 remains the trained baseline. |
| Serving | Vertex Endpoint REST from Dataflow (`--nlp_model vertex`). Weights are **not** `COPY`'d into the Flex Template image. |
| Registry | `stub` (default) and `vertex`. `events` was produced with `vertex` (XLM-R v2.1). DistilBERT v1, XLM-R v2 and v2.1 are uploaded to Model Registry; **no Endpoint exists today**. |
| Platform | Vertex AI Workbench / Model Registry / Endpoint (thesis Agent Platform). Console labels say Vertex AI; APIs are `aiplatform.googleapis.com` and `notebooks.googleapis.com`. |
| MLflow | Shipped as a file store on the Workbench VM + GCS artifacts. Superseded 2026-10-28 by a tracking server on Cloud Run + Cloud SQL (`terraform/modules/mlflow`, [ADR 0004](adr/0004-mlflow-tracking-server-on-cloud-run-and-cloud-sql.md)); artifacts unchanged. |

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

## Model Registry — XLM-R (21 Sep 2026)

| displayName | Model id | Versions | Artifact URI |
|---|---|---|---|
| `xlmr-sent` (v2) | `1068281099500650496` | 1 | `gs://co-tf-artifacts-dev/nlp/models/xlmr-sent` |
| `xlmr-sent-v2.1` | `406814904230608896` | 1, **2 (`default`)** | `gs://co-tf-artifacts-dev/nlp/models/xlmr-sent-v2.1` |

Both versions of `xlmr-sent-v2.1` point at the same artifact; version 2
is the one that was deployed. Selection rationale (gold_v3 holdout,
macro-F1 0.600 vs 0.568 for v2) is in
[`phase-1-nlp-xlmr-v2.1-continued.md`](phase-1-nlp-xlmr-v2.1-continued.md).

---

## Serve-replay: XLM-R v2.1 (21 Sep 2026)

Verified on 2026-10-11 from the audit log, the Dataflow job list and
BigQuery.

**Endpoint.** `co-nlp-endpoint-dev` was created at 10:44 UTC and
`xlmr-sent-v2.1@2` deployed on it (CPU, no accelerator). The audit log
shows `DeployModel` called several times between 10:45 and 11:10 UTC.

**Replays.** Four `co-replay-*` Dataflow jobs with `--model vertex` ran
between 19:00 and 20:47 UTC, all ending `Drained`:

| Job id | Created (UTC) |
|---|---|
| `2026-09-21_12_00_28-6503329829357441921` | 19:00 |
| `2026-09-21_12_26_41-12065803480988340445` | 19:26 |
| `2026-09-21_12_53_57-9372713233434302653` | 19:53 |
| `2026-09-21_13_28_48-7203928717638566170` | 20:28 |

**Result in BigQuery.**

| | |
|---|---|
| Rows in `events` | 12,254 — one per `id`, all `model_version = vertex/5203216677101109248` |
| Rows in `events` from the stub | 0 (the MERGE replaced them; stub rows remain only in `events_landing`) |
| Label split | 5923 `pos` / 4034 `neu` / 2297 `neg` (48 / 33 / 19 %) |
| Vertex rows in `events_landing` | 24,995 over 12,254 ids (the four runs overlap) |
| Ids classified more than once | 10,811 |
| …of which with a different label between runs | **3** |

`vertex/5203216677101109248` is the Endpoint's **deployed-model id**
(`VertexEndpointClassifier.model_version`, taken from the predict
response), not the Model Registry id. It maps to `xlmr-sent-v2.1@2`
through the deploy above. A future redeploy gets a new deployed-model id,
so `model_version` changes even if the weights do not.

The three disagreeing ids mean Endpoint inference is near-deterministic
but not bit-exact (cause not investigated). The reproducibility fingerprint in
[`phase-1-dataflow.md`](phase-1-dataflow.md) was demonstrated with the
stub; with the real model, expect a handful of borderline flips per
replay.

Per event:

| event_tag | n | pos | neu | neg |
|---|---:|---:|---:|---:|
| `xbox_showcase_reveal` | 1711 | 1039 | 585 | 87 |
| `gameplay_trailer_flying_waters` | 1257 | 679 | 473 | 105 |
| `xbox_developer_direct` | 292 | 190 | 86 | 16 |
| `launch` | 909 | 491 | 313 | 105 |
| `one_million_sales_milestone` | 477 | 276 | 129 | 72 |
| `critical_acclaim_wave` | 351 | 153 | 134 | 64 |
| `tga_2025_sweep` | 3328 | 1832 | 1046 | 450 |
| `indie_game_awards_rescinded` | 3502 | 966 | 1187 | 1349 |
| `anniversary_update_2026` | 427 | 297 | 81 | 49 |

`indie_game_awards_rescinded` is the only event where `neg` leads — the
first per-event difference in this project that reflects the model rather
than the plumbing.

**Language detection is noisy on short comments.** Of the 12,254 rows,
133 are tagged `af` and 73 `tl`; most are short English texts. The model
is multilingual, so classification is unaffected, but per-language
slices should treat the long tail with care.

**After the replay.** The Endpoint no longer exists in `europe-central2`
(checked 2026-10-11), so there is no replica billing. Workbench
`co-nlp-workbench-dev` is `STOPPED`. `nlp/catalog.py` still records
`co-nlp-endpoint-dev` as v2.1's Endpoint — that is where it was served,
not a live resource.

---

## Pending

- **Steam data.** `raw_staging` is still YouTube-only. Once Steam reviews
  are loaded, the next `vertex` replay needs the Endpoint recreated
  (`enable_nlp_endpoint=true`), v2.1 redeployed, and undeployed after the
  drain — the replay trigger
  (`co-replay-dev`, `--substitutions=_MODEL=vertex`) reads the Endpoint
  from Terraform and passes an empty value while none exists.
- **Weak-label evaluation (C2).** Steam `voted_up` against the model's
  labels — blocked on the Steam data above.

---

## Related

| Doc | Role |
|---|---|
| [`nlp/README.md`](../nlp/README.md) | Train, register, deploy, launch |
| [`terraform/modules/vertex_nlp/README.md`](../terraform/modules/vertex_nlp/README.md) | Gates, IAM, IAP SSH, cost runbook |
| [`phase-1-nlp-evaluation-distilbert-v1.md`](phase-1-nlp-evaluation-distilbert-v1.md) | DistilBERT v1 gold metrics |
| [`phase-1-dataflow.md`](phase-1-dataflow.md) | Pipeline, MERGE and reproducibility (demonstrated with the stub) |
| [`phase-1-plan.md`](phase-1-plan.md) | Track C (C1–C3 superseded; pointer here) |

## Serving CPU quota is per machine family (2026-10-17)

Deploying a replica for the full two-source replay failed on every
machine size, down to 2 vCPU:

```
429 CustomModelServingCPUsPerProjectPerRegion 8: quota exceeded
```

Nothing was deployed at the time. Monitoring showed the allocation pinned
at **8 of 8 since 10 October** — it never came back after the Endpoint
was deleted on the 12th. No orphaned deployment is visible through the
API, so the allocation is stuck on Google's side and only a quota request
or support ticket would clear it.

**It did not have to be cleared.** Vertex counts serving CPUs *per
machine family*, and the project has separate, untouched pools:

| Quota | Limit | State |
|---|---|---|
| Custom model serving CPUs (N1 / aggregate) | 8 | stuck at 8/8 |
| Custom model serving **N2** CPUs | 8 | free |
| Custom model serving **N2D** CPUs | 8 | free |

An `n2-standard-4` deployed immediately. Beyond unblocking, this is also
how to go faster than the original setup: one model served from **two
families at once** — `n2-standard-8` and `n2d-standard-8` at 50% traffic
each — is 16 vCPU against the 8 vCPU of the single `n1-standard-8` used
for the first replay. Both serve identical weights, so a split changes
throughput and nothing else.

`nlp/endpoint/register.py` takes `--traffic-percentage` for exactly this.
Undeploy both when the replay drains; an empty Endpoint does not bill.
