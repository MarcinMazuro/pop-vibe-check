# modules/vertex_nlp

Vertex AI pieces for DistilBERT sentiment: a gated Workbench instance
for fine-tuning (CPU-only by default), a gated serving Endpoint, and the
IAM that lets the ML trainer upload models and the Dataflow worker call
`predict`.

This is the Agent Platform stack from the thesis (Workbench / Model
Registry / Endpoint). Console labels say Vertex AI; the APIs are
`aiplatform.googleapis.com` and `notebooks.googleapis.com`.

## What this creates

Always (cheap, not gated):

- **`roles/aiplatform.user`** (project) for the ML trainer SA — Model.upload, Endpoint.deploy.
- **`roles/iam.serviceAccountUser`** on the trainer SA for the notebooks service agent — required to attach that SA to a Workbench VM.
- **`roles/aiplatform.user`** (project) for the Dataflow worker SA — Endpoint.predict. Private Google Access on the subnet is enough; workers have no public IP.

Gated, default **off** (`count = 0`). A routine `terraform apply` must
never start a GPU:

| Resource | Gate | Default |
|---|---|---|
| `google_workbench_instance` (`e2-standard-4`, **no** `accelerator_configs`, `europe-central2-b`) | `enable_workbench` | `false` |
| `google_compute_firewall` IAP SSH (`35.235.240.0/20` → TCP 22, tag `workbench`) | `enable_workbench` | `false` |
| `google_vertex_ai_endpoint` (empty; no deployed replica) | `enable_endpoint` | `false` |

`workbench_accelerator_count` defaults to `0`, so `accelerator_configs`
is omitted and a plan cannot mention NVIDIA / T4. GPU training is opt-in
(`count=1` + `NVIDIA_TESLA_T4` + typically `n1-standard-8`) and is blocked
on free-tier billing.

Even with `enable_workbench=true`, `workbench_desired_state` defaults to
`STOPPED`, so creating the VM does not burn hours until an operator
sets `ACTIVE` (or starts it in the console). Idle shutdown is 3 hours
(`idle-timeout-seconds`).

**Terraform does not store model versions.** Uploading DistilBERT to
Vertex AI Model Registry and deploying a replica onto the Endpoint are
training-artifact steps (`nlp/endpoint/register.py`). Putting a deployed
model in state would make `terraform apply` the thing that starts GPU
serving — the same accident this module's gates exist to prevent.

## Cost runbook

Workbench (CPU, or T4 if opted in) and an Endpoint replica are the
second cost line after streaming Dataflow. The intended session is:

1. Set `enable_workbench=true` (and `workbench_owners`) → apply → start the instance (`desired_state=ACTIVE` or console Start). Default machine is `e2-standard-4` with **no** GPU.
2. Train on Workbench (see `nlp/README.md`). Stop the instance when the run finishes — do not leave it idle. Idle shutdown is a backstop, not a plan.
3. `python -m nlp.endpoint.register upload …` → Model Registry.
4. Set `enable_endpoint=true` → apply (creates the empty Endpoint).
5. `python -m nlp.endpoint.register deploy …` → one replica, T4 or CPU, `min_replica_count=1`.
6. Dataflow replay with `--model vertex`.
7. Drain Dataflow.
8. Undeploy the replica (`python -m nlp.endpoint.register undeploy …`). An empty Endpoint does not bill for GPU.
9. Stop Workbench. Optionally set both gates back to `false` and apply so the next operator cannot forget a running VM.

Do **not** `terraform apply` with these gates on as part of a routine infra change.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | GCP project ID |
| `name_prefix` | string | yes | — | Short release prefix (2-8 chars) |
| `env` | string | yes | — | Environment name; suffixed into resource names |
| `region` | string | yes | — | Endpoint / Model Registry region (`europe-central2`) |
| `labels` | map(string) | yes | — | Labels on Workbench and Endpoint |
| `trainer_sa_email` | string | yes | — | ML trainer SA |
| `dataflow_worker_sa_email` | string | yes | — | Dataflow worker SA (predict) |
| `network_id` | string | yes | — | VPC id for Workbench |
| `subnet_id` | string | yes | — | Subnet id for Workbench (PGA, no public IP) |
| `enable_workbench` | bool | no | `false` | Create the Workbench instance |
| `workbench_zone` | string | no | `europe-central2-b` | Must be `-b` or `-c` |
| `workbench_machine_type` | string | no | `e2-standard-4` | GCE machine type (CPU). `e2-standard-8` if RAM is tight |
| `workbench_accelerator_type` | string | no | `""` | Empty when count is 0. `NVIDIA_TESLA_T4` only when count is 1 |
| `workbench_accelerator_count` | number | no | `0` | `0` omits `accelerator_configs` (CPU-only) |
| `workbench_idle_timeout_seconds` | number | no | `10800` | Idle shutdown |
| `workbench_desired_state` | string | no | `STOPPED` | `ACTIVE` or `STOPPED` |
| `workbench_owners` | list(string) | no | `[]` | Emails that can open Jupyter |
| `enable_endpoint` | bool | no | `false` | Create the empty Endpoint |

## Outputs

| Name | Description |
|---|---|
| `trainer_sa_email` | Echo of the trainer SA |
| `workbench_enabled` / `workbench_name` / `workbench_id` / `workbench_zone` | Workbench identity; name/id empty when gated off |
| `endpoint_enabled` / `endpoint_id` / `endpoint_resource_name` | Endpoint identity; empty when gated off |
| `location` | Vertex AI region |

`endpoint_resource_name` is what `dataflow/launch.sh --model vertex` passes
as `VERTEX_ENDPOINT_ID`.

## Networking

Workbench and Dataflow workers sit on `co-vpc-dev` / `co-subnet-dev` with
**Private Google Access** and **no public IP**. That is enough for
`aiplatform.googleapis.com`, `notebooks.googleapis.com`, GCS, BigQuery,
and Artifact Registry. There is still no path to PyPI or Hugging Face Hub
from a Dataflow worker — training downloads happen on Workbench (which
operators start with console access) or from a pre-cached
`gs://…/nlp/datasets/` prefix.

### SSH over IAP

The custom-mode VPC has no default allow-ssh. With `enable_workbench=true`
this module adds `{name_prefix}-allow-workbench-iap-ssh-{env}`: ingress
from `35.235.240.0/20` (IAP TCP forwarding) to TCP 22, target tag
`workbench`. Jupyter still works through the Vertex console proxy.

From a laptop with `gcloud` (replace the project if needed):

```bash
gcloud workbench instances ssh co-nlp-workbench-dev \
  --project=pop-vibe-check \
  --location=europe-central2-b

# equivalent, if the GCE VM keeps the same name:
gcloud compute ssh jupyter@co-nlp-workbench-dev \
  --project=pop-vibe-check \
  --zone=europe-central2-b \
  --tunnel-through-iap
```

The caller needs `roles/iap.tunnelResourceAccessor` (or equivalent) on the
project or instance. Do not add a public IP or Cloud NAT to reach this VM.

## Related grants (other modules)

| Grant | Where |
|---|---|
| Trainer `objectAdmin` on the artifacts bucket (`nlp/` cache + MLflow) | `storage/` |
| Trainer `dataViewer` + `jobUser` on the analytics dataset | `bigquery/` |
| Trainer `artifactregistry.writer` on the image repo | `artifact_registry/` (via `writer_sa_emails`) |
| Dataflow worker `aiplatform.user` | **here** |
