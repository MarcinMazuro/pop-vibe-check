# terraform/bootstrap

One-time, manually-applied Terraform configuration. Creates the two pieces
of shared infrastructure that every other Terraform run in this repo
depends on:

1. **One** GCS bucket that hosts Terraform remote state for every
   environment and every case study (`pvc-tf-state` by default). State is
   separated by object prefix inside the bucket — `dev/`, `prod/`,
   `dev-w4/`, etc.
2. **One** long-lived service account (`pvc-tf-runner-sa`) that every later
   `terraform apply` impersonates, regardless of which environment or
   release it operates on.

Bootstrap is run **once per GCP project**, not once per environment.

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

### 3. Enable the bootstrap-prerequisite APIs

Terraform cannot enable an API it cannot call. Three APIs must be on **by
hand** before the first ever apply against a brand-new project:

```bash
gcloud services enable \
  cloudresourcemanager.googleapis.com \
  iam.googleapis.com \
  serviceusage.googleapis.com
```

Once bootstrap is applied, the full set of services this project needs
(`iamcredentials`, `storage`, `bigquery`, `run`, `cloudbuild`,
`artifactregistry`, `pubsub`, `dataflow`, `secretmanager`, `compute`,
`billingbudgets`, plus the three above) is managed declaratively by
`google_project_service` resources in this module and survives the GCP
"unused API auto-disable" sweep — any future `terraform apply` re-enables
whatever lapsed. The full list lives in `var.enabled_services` if you ever
need to add or remove one.

API enablement can take a minute or two to propagate after the command
returns.

---

## Configure variables

Only `project_id` is required on a fresh run; everything else has a sensible
default.

| Variable | Required | Default | Description |
|---|---|---|---|
| `project_id` | yes | — | GCP project ID. `gcloud config get-value project` to find. |
| `billing_account_id` | no | `""` | `XXXXXX-YYYYYY-ZZZZZZ`. When set, the runner SA is granted `roles/billing.costsManager` so budget alerts can be created later. Find with `gcloud billing accounts list`. |
| `name_prefix` | no | `pvc` | Short prefix for the state bucket and runner SA. Override if `pvc-tf-state` turns out to be globally taken in GCS. |
| `region` | no | `europe-central2` | Region for the state bucket. |
| `operator_emails` | no | `[]` | Emails granted `serviceAccountTokenCreator` on the runner SA so they can impersonate it from `envs/*`. Empty list = manual `gcloud` grant required per operator. |
| `force_destroy_state_bucket` | no | `false` | One-off escape hatch for `terraform destroy` when the state bucket still has objects. See "Tearing down" below. |
| `enabled_services` | no | full Phase 0+1 set | Set of GCP APIs Terraform keeps enabled on the project. Defaults cover everything the planned modules need; override only to add a service. |

If `billing_account_id` is empty, the runner SA does **not** receive
billing-account-level permissions. That is fine for the very first apply, but
later modules that create budget alerts will need a human to fill this in
and re-apply bootstrap to grant the missing role.

**`name_prefix` is also referenced in `terraform/envs/*/backend.tf` and
`providers.tf` as a literal.** If you override the default here, you must
also update those files (the GCS backend block does not accept variable
interpolation).

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

A clean `plan` on a fresh project with `billing_account_id` set and one
entry in `operator_emails` should show **32 resources to add**:

- 15 × `google_project_service` (one per entry in `var.enabled_services` — includes `monitoring.googleapis.com` since the budgets module landed)
- 1 × `google_storage_bucket` (the state bucket)
- 1 × `google_service_account` (the runner SA)
- 14 × `google_project_iam_member` (one per curated role on the project, including `compute.securityAdmin` for the Dataflow inter-worker firewall rule)
- 1 × `google_billing_account_iam_member` (only if `billing_account_id` is set)
- N × `google_service_account_iam_member` (one per operator email)

On a re-apply, `google_project_service` resources are noops unless an API
was disabled out-of-band — in which case the apply re-enables it.

Record the values printed by `terraform output` — the next configuration
under `terraform/envs/dev/` will reference `state_bucket_name` in its
backend block, and the runner SA email when configuring provider
impersonation.

---

## Tearing down

`force_destroy = false` is the default on the state bucket — GCS will refuse
to delete a bucket that still has objects in it (including noncurrent
versions, since versioning is on). That is a deliberate barrier against
accidentally nuking production state.

When you genuinely want to recreate the bucket (e.g. renaming, migrating
to a different prefix, blowing away a dev project), set the override on
the CLI for both the apply that lifts the barrier and the destroy itself:

```bash
terraform apply  -var="force_destroy_state_bucket=true" -auto-approve
terraform destroy -var="force_destroy_state_bucket=true" -auto-approve
```

The default flips back to `false` automatically on the next normal apply —
no code edit required, no risk of leaving the bucket unprotected.

---

## Grant operators impersonation rights

Once bootstrap is applied, the long-lived runner SA exists but **no human
can yet impersonate it**. Every operator who will run `terraform` against
`envs/*` needs the role `roles/iam.serviceAccountTokenCreator` on the
runner SA. `roles/owner` does **not** satisfy this — Owner intentionally
excludes `iam.serviceAccounts.getAccessToken`.

**Recommended:** declare the operator list in `terraform.tfvars` so the
grants are tracked by Terraform:

```hcl
operator_emails = [
  "you@example.com",
  "teammate@example.com",
]
```

A re-apply of bootstrap then creates one
`google_service_account_iam_member` per email, granting the required
role. Adding or removing operators later = edit the list, re-apply.

**Manual fallback** (if you prefer not to track the list in Terraform):

```bash
gcloud iam service-accounts add-iam-policy-binding \
  pvc-tf-runner-sa@<PROJECT_ID>.iam.gserviceaccount.com \
  --member="user:<operator-email>" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --project=<PROJECT_ID>
```

The Terraform-managed grants and manual grants do not conflict (the
binding is keyed by member, not exclusive) — but mixing them is a
maintenance trap. Pick one approach per project.

---

## After apply (cleanup)

Bootstrap is meant to be applied **once per GCP project** and then left
alone. Every later environment or case study shares the same state bucket
and runner SA — re-applying bootstrap is for adding roles to the runner SA
or recovering from a destroy, not for onboarding new envs.

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
   work happens under `terraform/envs/<env>/` using the remote state bucket
   this run created. Come back to `terraform/bootstrap/` only to:
   - add a role to the runner SA's curated list,
   - rotate the runner SA, or
   - recover from a destroy.

   Onboarding a new environment (`prod`) or a new case study (e.g.
   `dev-w4/`) does **not** require re-applying bootstrap — they just use a
   different `prefix` in their backend block, against the same bucket.

---

## Outputs

| Output | What it is | Used by |
|---|---|---|
| `state_bucket_name` | Name of the remote-state bucket | `terraform/envs/*/backend.tf` |
| `state_bucket_url`  | `gs://` URL of the same bucket | reference / debugging |
| `runner_service_account_email` | Long-lived runner SA email | provider impersonation in `terraform/envs/*` |
| `runner_service_account_id` | Fully-qualified runner SA resource ID | IAM bindings in later modules |
