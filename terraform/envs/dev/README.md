# terraform/envs/dev

Composition root for the **dev** GCP environment. Every Phase 0 and Phase 1
module is wired in from this directory. State is stored remotely in the GCS
bucket provisioned by `terraform/bootstrap`, and every apply impersonates the
long-lived `pvc-tf-runner-sa` service account.

**Applies go through Cloud Build, not laptops.** A pull request touching
`terraform/**` runs `terraform plan` in CI; merging it to `main` queues
`terraform apply`, which starts once an approver releases it in the Cloud
Build console. Locally you run `terraform plan` only. See
"Plan / apply" below.

---

## Prerequisites

- `terraform/bootstrap` has been applied successfully against this project
  (state bucket `pvc-tf-state` and SA `pvc-tf-runner-sa` exist).
- `gcloud` and `terraform` (`>= 1.6, < 2.0`) installed.
- You hold `roles/iam.serviceAccountTokenCreator` on the runner SA. The
  provider impersonates the SA on every apply, and impersonation requires
  this role on your user identity. **`roles/owner` is not enough** — that
  role intentionally excludes `iam.serviceAccounts.getAccessToken` so an
  Owner cannot silently impersonate every SA in the project. Grant it
  once per operator with:

  ```bash
  gcloud iam service-accounts add-iam-policy-binding \
    pvc-tf-runner-sa@<PROJECT_ID>.iam.gserviceaccount.com \
    --member="user:<your-email>" \
    --role="roles/iam.serviceAccountTokenCreator" \
    --project=<PROJECT_ID>
  ```

### One-time auth

```bash
gcloud auth login                              # gcloud CLI
gcloud auth application-default login          # ADC, used by Terraform
gcloud config set project <PROJECT_ID>
```

### Configure variables

The canonical `terraform.tfvars` for dev lives in Secret Manager as
`co-tfvars-dev` — it is what CI applies. Pull it into this directory
instead of writing your own, so a local plan sees the same inputs:

```bash
gcloud secrets versions access latest --secret=co-tfvars-dev \
  --project=<PROJECT_ID> > terraform.tfvars
```

`terraform.tfvars` is excluded by the repository `.gitignore`;
`terraform.tfvars.example` documents the shape.

**Changing a variable** (budget, alert emails, the Workbench flags,
approvers) means publishing a new secret version and re-running the
apply trigger:

```bash
$EDITOR terraform.tfvars
gcloud secrets versions add co-tfvars-dev --project=<PROJECT_ID> \
  --data-file=terraform.tfvars
gcloud builds triggers run co-terraform-apply-dev \
  --region=europe-central2 --branch=main
```

The run still waits for approval.

### Case-study prefix (`name_prefix`)

The composition takes an optional `name_prefix` variable (default `"co"`
for Clair Obscur: Expedition 33). It is prepended to every
release-specific resource name — buckets, datasets, topics, workload
service accounts — so multiple case studies can live in the same GCP
project without name collisions.

The universal state bucket (`pvc-tf-state`) and runner SA
(`pvc-tf-runner-sa`) created by `terraform/bootstrap` are **not** affected
by `name_prefix` — they are shared infrastructure across every release and
every environment. `name_prefix` only flows into release-scoped resources
(buckets, datasets, topics, workload SAs).

**If you want to analyse a different release** (e.g. `name_prefix = "w4"`
for Witcher 4): use a separate Terraform state by either creating a
sibling composition directory (e.g. `terraform/envs/dev-w4/` with its
own `backend.tf` prefix) or by using `terraform workspace`. Re-running
this directory with a different `name_prefix` against the **same** state
would replace the existing resources, which is almost never what you
want.

---

## Init

```bash
terraform init
```

Initial init pulls the provider plugin and configures the GCS backend
against the universal state bucket `pvc-tf-state` with prefix `dev/`. If
the bucket does not yet exist, init will fail with a clear error —
re-apply `terraform/bootstrap` first.

---

## Plan / apply

```bash
terraform plan
```

On a clean `main`, the plan should print **`No changes.`** A diff means
drift — someone changed a resource outside Terraform, or your local
`terraform.tfvars` differs from the secret.

Applies happen in Cloud Build (`co-terraform-apply-dev`, runs as
`pvc-tf-ci-sa`, which impersonates the runner SA just like a laptop does):

1. Open a PR. `co-terraform-plan-pr-dev` runs `fmt -check`, `validate` for
   bootstrap and this env, and `plan`; the full plan is in the build log
   linked from the PR check.
2. Merge. `co-terraform-apply-dev` is queued **awaiting approval**.
3. An approver (`cloud_build_approver_emails`) approves it in the Cloud
   Build console (History → the build → Approve). The build plans again
   against current state and applies exactly that plan.

   From a terminal, the approval is an API call — `gcloud builds approve`
   only exists in the alpha/beta channels:

   ```bash
   BUILD=$(gcloud builds list --region=europe-central2 \
     --filter='substitutions.TRIGGER_NAME=co-terraform-apply-dev AND status=PENDING' \
     --limit=1 --format='value(id)')
   curl -s -X POST -H "Authorization: Bearer $(gcloud auth print-access-token)" \
     -H 'Content-Type: application/json' \
     -d '{"approvalResult":{"decision":"APPROVED"}}' \
     "https://cloudbuild.googleapis.com/v1/projects/<PROJECT_ID>/locations/europe-central2/builds/$BUILD:approve"
   ```

Approval happens before the build starts, so the applied plan is fresh,
not the one from the PR; read the apply log if state moved in between.

Local `terraform apply` is reserved for bootstrapping CI itself (the
connection and triggers cannot apply themselves the first time) and for
recovering from a broken CI.

---

## How to add a module

When a module under `terraform/modules/<name>/` is ready, wire it up here:

1. Add a `module "<name>" { source = "../../modules/<name>" ... }` block in
   [main.tf](main.tf), passing `env = local.env`, `project_id = var.project_id`,
   `region = var.region`, `labels = local.labels`, plus any module-specific
   inputs.
2. Surface anything downstream consumers need via [outputs.tf](outputs.tf).
3. Run `terraform plan` locally before opening the PR — every new module
   should produce a reviewable diff. CI plans it again on the PR and
   applies it after merge.

---

## Files

| File | Purpose |
|---|---|
| [versions.tf](versions.tf) | Pins Terraform and provider versions |
| [backend.tf](backend.tf) | GCS remote state configuration |
| [providers.tf](providers.tf) | Google provider + runner SA impersonation |
| [variables.tf](variables.tf) | Input variables |
| [main.tf](main.tf) | Composition root (modules wired here) |
| [outputs.tf](outputs.tf) | Outputs (added alongside modules) |
| [terraform.tfvars.example](terraform.tfvars.example) | Template for local `terraform.tfvars` |
