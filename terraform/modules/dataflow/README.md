# modules/dataflow

IAM and launch parameters for the Dataflow streaming pipeline. This module owns the Dataflow-specific bits that don't belong to the modules provisioning the resources the job touches — the network, the temp bucket, the Pub/Sub subscription/DLQ, the BigQuery tables. Those live in their own modules; this one wires the identities and hands PR 3 a tidy set of launch parameters.

## What this creates

- **`roles/dataflow.worker`** (project scope) for the Dataflow worker SA — the standard grant that lets a SA run as a Dataflow worker.
- **`roles/dataflow.admin`** (project scope) for the launcher principal — create/manage jobs.
- **`roles/iam.serviceAccountUser`** on the worker SA for the launcher — "actAs" the worker SA so a launch can submit a job that runs as it. Missing this grant is the classic `serviceAccounts.actAs` launch failure.
- **Outputs** composing every value a `gcloud dataflow flex-template run` needs (see "Launch parameters" and "Launching" below).

The worker SA's rights on the data it actually touches are granted next to those resources, not here:

| Grant | Where |
|---|---|
| `roles/pubsub.subscriber` on the Dataflow subscription, `roles/pubsub.publisher` on the DLQ topic | `pubsub/` |
| `roles/bigquery.dataEditor` on the dataset, `roles/bigquery.jobUser` (project) | `bigquery/` |
| `roles/storage.objectAdmin` on the dataflow-temp bucket | `storage/` |
| `roles/artifactregistry.reader` on the image repo | `artifact_registry/` (via `reader_sa_emails`) |
| `roles/dataflow.worker` (project) | **here** |

## No `google_dataflow_flex_template_job` — on purpose

This module does **not** create a Dataflow job resource, and PR 1 must not. Two reasons:

1. **Nothing to point it at yet.** The Flex Template image and its spec JSON are built in PR 3.
2. **`terraform apply` must never start a streaming job.** A streaming Dataflow job runs and bills continuously until it is drained — it is the single most expensive resource in this project. Binding it to `terraform apply` would mean a routine apply (say, adding a label) starts it. That is the exact accident this PR's structure avoids.

So the launch stays out of Terraform for now. PR 3 runs `gcloud dataflow flex-template run` with the parameters this module outputs, and decides then whether to promote the launch into a Terraform resource. If it does, that resource must be **gated on a variable defaulting to `null`** (so it is `count = 0` until an operator opts in) — the same shape `cloud_run_jobs` uses to keep `reddit_image_uri` on a placeholder until a real image exists. It never defaults to on.

## Private networking — why the image must be self-contained

The pipeline is launched with **`--no-use-public-ips`**. Workers get no external IP; they reach Pub/Sub, BigQuery, GCS, and Artifact Registry over **Private Google Access** (enabled on the subnet by the `network` module). This keeps the workers off the public internet and inside the VPC.

The consequence for PR 3: **the Flex Template image must be self-contained.** With no public egress there is no PyPI at runtime — every Python dependency, and any model file a component needs (for example a language-detection model, now that language detection is authoritative in `events` and done in the pipeline), must be **baked into the image at build time**, not downloaded when the worker starts. A worker that tries to `pip install` or fetch a model URL at runtime will hang and time out.

(The `dataflow` network tag the workers carry is what the `network` module's inter-worker firewall rule targets — Dataflow applies it automatically.)

## Launch parameters

`terraform output` (at the env level, which re-exports this module) yields:

| Output | `gcloud dataflow flex-template run` flag |
|---|---|
| `worker_sa_email` | `--service-account-email` |
| `region` | `--region` |
| `subnetwork` | `--subnetwork` |
| `temp_location` | `--temp-location` |
| `staging_location` | `--staging-location` |
| `template_spec_dir` | prefix the built spec JSON is uploaded under (`--template-file-gcs-location` points at a file here) |
| `input_subscription` | `--parameters input_subscription=…` |
| `dlq_topic` | `--parameters dlq_topic=…` |
| `events_landing_table` | `--parameters output_table=…` (the pipeline's write target) |
| `events_table` | MERGE target (not a Dataflow write target; provided so the promotion step reads it from one place) |
| `worker_network_tag`, `network` | informational / verification |

Plus the hard requirement above: `--no-use-public-ips`, matched by `--disable-public-ips` on the `gcloud` launch.

## Launching (PR 3, illustrative)

Once the template is built and its spec uploaded under `template_spec_dir`:

```bash
cd terraform/envs/dev
REGION=$(terraform output -raw dataflow_region)
gcloud dataflow flex-template run "co-sentiment-$(date +%Y%m%d-%H%M%S)" \
  --template-file-gcs-location="$(terraform output -raw dataflow_template_spec_dir)/spec.json" \
  --region="$REGION" \
  --service-account-email="$(terraform output -raw dataflow_worker_sa_email)" \
  --subnetwork="$(terraform output -raw dataflow_subnetwork)" \
  --temp-location="$(terraform output -raw dataflow_temp_location)" \
  --staging-location="$(terraform output -raw dataflow_staging_location)" \
  --disable-public-ips \
  --parameters="input_subscription=$(terraform output -raw dataflow_input_subscription),output_table=$(terraform output -raw dataflow_events_landing_table),dlq_topic=$(terraform output -raw dataflow_dlq_topic)"
```

The exact output names are the env-level ones (`dataflow_*`); parameter names (`input_subscription`, `output_table`, `dlq_topic`) are the Beam pipeline's to define in PR 3.

## Inputs

| Name | Type | Required | Default | Description |
|---|---|---|---|---|
| `project_id` | string | yes | — | GCP project ID |
| `region` | string | yes | — | Region the job runs in |
| `dataflow_worker_sa_email` | string | yes | — | Worker SA; granted `dataflow.worker` and set as the launcher's actAs target |
| `launcher_sa_email` | string | yes | — | Principal that launches jobs; granted `dataflow.admin` + `serviceAccountUser` on the worker SA |
| `subnetwork_self_link` | string | yes | — | Subnet self-link → `--subnetwork` |
| `network_self_link` | string | yes | — | VPC self-link (informational) |
| `worker_network_tag` | string | yes | — | Network tag the inter-worker firewall rule targets |
| `dataflow_temp_bucket_url` | string | yes | — | `gs://` URL of the dataflow-temp bucket; temp/staging/template locations compose from it |
| `bq_dataset_id` | string | yes | — | Short dataset id used to compose table refs |
| `events_landing_table_id` | string | yes | — | Short id of the Dataflow write target |
| `events_table_id` | string | yes | — | Short id of the analytical events table (MERGE target) |
| `dataflow_subscription_id` | string | yes | — | Full subscription resource id the pipeline consumes |
| `dlq_topic_id` | string | yes | — | Full DLQ topic resource id the pipeline publishes to |

## Outputs

See "Launch parameters" above — every output maps to a launch flag or parameter.

## Notes

- **The Dataflow service agent** (`service-<project_number>@dataflow-service-producer-prod.iam.gserviceaccount.com`) gets `roles/dataflow.serviceAgent` automatically when the Dataflow API is enabled; it is not managed here.
- **Launcher choice.** The launcher is wired to the Cloud Build SA in `envs/dev` — the roadmap's eventual CI launcher. For a manual dev launch before CI exists, impersonate that SA (`gcloud … --impersonate-service-account=<cloud-build-sa>`) to inherit `dataflow.admin` + actAs, mirroring how `terraform apply` impersonates the runner SA. The launcher also needs read on the template spec object under `template_spec_dir`; that comes with the Cloud Build module (or operator perms).
