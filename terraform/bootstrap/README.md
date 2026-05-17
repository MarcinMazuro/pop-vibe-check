# terraform/bootstrap

One-time, manually-applied Terraform configuration. Creates the two things
every other Terraform run in this repo depends on:

1. The GCS bucket that hosts Terraform remote state (`co-tf-state-dev`).
2. The long-lived service account (`co-tf-runner-sa`) that every later
   `terraform apply` uses.

This is the **only** configuration in the repo that uses a **local** Terraform
backend, because nothing else exists yet to store remote state in. After this
runs, the resulting `terraform.tfstate` file in this directory is the only
record of the bootstrap resources — keep it somewhere durable.

---

## Prerequisites

- A GCP project (existing or freshly created in the console).
- A billing account linked to that project.
- `gcloud` CLI installed and on `PATH`.
- Terraform `>= 1.6, < 2.0` installed and on `PATH`.

### 1. Pick or create the project

```bash
gcloud projects create <PROJECT_ID>           # skip if the project exists
gcloud billing accounts list                  # find the ID: XXXXXX-YYYYYY-ZZZZZZ
gcloud billing projects link <PROJECT_ID> \
  --billing-account=<BILLING_ACCOUNT_ID>
gcloud config set project <PROJECT_ID>
```

### 2. Authenticate

User identity:

```bash
gcloud auth login                              # gcloud CLI
gcloud auth application-default login          # Terraform / Google SDKs
```

Or, if you are using a downloaded bootstrap SA key instead:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/bootstrap-sa.json
```

Application Default Credentials are what Terraform actually reads.

### 3. Enable the required APIs

Terraform's `google_project_iam_member` resources depend on IAM and Service
Usage already being on, so the APIs must be enabled manually before the
first apply:

```bash
gcloud services enable \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  serviceusage.googleapis.com \
  compute.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  pubsub.googleapis.com \
  dataflow.googleapis.com \
  bigquery.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  billingbudgets.googleapis.com
```

API enablement can take a minute or two to propagate after the command
returns.

---

## Configure variables

Two values matter on the first run; `env` defaults to `dev` and `region` to
`europe-central2`, which is correct for the standard case.

| Variable | Required | Value | How to find it |
|---|---|---|---|
| `project_id` | yes | GCP project ID (a string, not the project number) | `gcloud config get-value project` |
| `billing_account_id` | optional | `XXXXXX-YYYYYY-ZZZZZZ` | `gcloud billing accounts list` |
| `env` | no | `dev` or `prod` (default `dev`) | — |
| `region` | no | default `europe-central2` | — |

If `billing_account_id` is empty, the runner SA does **not** receive
billing-account-level permissions. That is fine for the very first apply, but
later modules that create budget alerts will need a human to fill this in
and re-apply bootstrap to grant the missing role.

The repository's `.gitignore` excludes `*.tfvars`, so the idiomatic place to
put these values is a local `terraform.tfvars` file in this directory:

```hcl
# terraform/bootstrap/terraform.tfvars
project_id         = "your-gcp-project-id"
billing_account_id = "XXXXXX-YYYYYY-ZZZZZZ"   # remove this line if not yet known
```

Alternatives if you'd rather not keep a file on disk:

```bash
# Option B — pass on every command
terraform apply \
  -var="project_id=…" \
  -var="billing_account_id=…"

# Option C — environment variables
export TF_VAR_project_id="…"
export TF_VAR_billing_account_id="…"
terraform apply
```

---

## Apply

From this directory:

```bash
terraform init
terraform plan          # review the plan; see expected resources below
terraform apply
```

A clean `plan` with `billing_account_id` set should show **15 resources to
add**:

- 1 × `google_storage_bucket` (the state bucket)
- 1 × `google_service_account` (the runner SA)
- 13 × `google_project_iam_member` (one per curated role)
- 1 × `google_billing_account_iam_member` (only if `billing_account_id` is set)

Record the values printed by `terraform output` — the next configuration
under `terraform/envs/dev/` will reference `state_bucket_name` in its
backend block, and the runner SA email when configuring provider
impersonation.

---

## After apply (cleanup)

Bootstrap is meant to be applied once per environment and then left alone.

1. **Delete the bootstrap SA key** if you used one:

   ```bash
   gcloud iam service-accounts keys list \
     --iam-account=bootstrap-sa@<PROJECT_ID>.iam.gserviceaccount.com
   gcloud iam service-accounts keys delete <KEY_ID> \
     --iam-account=bootstrap-sa@<PROJECT_ID>.iam.gserviceaccount.com
   ```

   Shred the JSON file locally afterwards.

2. **Preserve `terraform.tfstate`.** This directory's state file is the only
   record of the bootstrap resources. It contains no secret material for
   this configuration — just the bucket name and SA email — so it can be
   stored either by committing it to a private location outside this repo,
   or kept off-cluster (a password manager attachment, a private bucket,
   etc.). Without it, destroying these resources later requires manual
   `gcloud` cleanup.

3. **Do not re-apply bootstrap on every change.** From here on, infrastructure
   work happens under `terraform/envs/dev/` using the remote state bucket
   this run created. Come back to `terraform/bootstrap/` only to:
   - add a role to the runner SA's curated list,
   - rotate the runner SA,
   - bootstrap a new environment (e.g. `prod`), or
   - recover from a destroy.

---

## Outputs

| Output | What it is | Used by |
|---|---|---|
| `state_bucket_name` | Name of the remote-state bucket | `terraform/envs/*/backend.tf` |
| `state_bucket_url`  | `gs://` URL of the same bucket | reference / debugging |
| `runner_service_account_email` | Long-lived runner SA email | provider impersonation in `terraform/envs/*` |
| `runner_service_account_id` | Fully-qualified runner SA resource ID | IAM bindings in later modules |
